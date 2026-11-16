"""Integration test: import a fixture into RethinkDB (database ``RETHINK_DB``, default ``mlp_test_parser``)."""
import asyncio
import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FIXTURES

from mlp import settings, core
from mlp import main as mlp_main


def _rethink_up() -> bool:
    try:
        with socket.create_connection((settings.rethink_host, settings.rethink_port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _rethink_up(), reason='RethinkDB is not reachable')


def _reset_connection():
    # get_rethink() caches the connection, which is bound to the event loop that created it
    getattr(core, '__STORE').clear()


async def _drop_db():
    from rethinkdb import RethinkDB
    r = RethinkDB()
    r.set_loop_type('asyncio')
    conn = await r.connect(settings.rethink_host, settings.rethink_port)
    try:
        if settings.rethink_db in await r.db_list().run(conn):
            await r.db_drop(settings.rethink_db).run(conn)
    finally:
        await conn.close()


async def _fetch(doc_id):
    db, conn, r = await core.get_rethink()
    doc = await db.table('sent_mail').get(doc_id).run(conn)
    count = await db.table('sent_mail').count().run(conn)
    indexes = await db.table('sent_mail').index_list().run(conn)
    # get_rethink() creates indexes without waiting for them
    await db.table('sent_mail').index_wait('host').run(conn)
    by_host = await db.table('sent_mail').get_all('mx2', index='host').count().run(conn)
    return doc, count, indexes, by_host


@pytest.fixture
def db(monkeypatch, tmp_path):
    assert settings.rethink_db.startswith('mlp_test'), 'refusing to run against a non-test database'
    lock = str(tmp_path / 'run' / 'processing.lock')
    monkeypatch.setattr(settings, 'mail_log_path', FIXTURES)
    monkeypatch.setattr(settings, 'mail_log_filenames', ['postfix_rfc3339.log', 'does-not-exist.log'])
    monkeypatch.setattr(settings, 'gui_refresh_block', True)
    monkeypatch.setattr(settings, 'housekeeping_days', '')
    monkeypatch.setattr(settings, 'import_batch_size', 4)
    monkeypatch.setattr(mlp_main, 'lockfile', lock)
    _reset_connection()
    asyncio.run(_drop_db())
    yield lock
    _reset_connection()
    asyncio.run(_drop_db())


def test_import_into_rethinkdb(db):
    lock = db

    async def run():
        await mlp_main.main()
        assert not os.path.exists(lock), 'lock file must be removed after the run'
        first = await _fetch('mx1:25CF61E7BCF')
        # a second run updates the same documents instead of duplicating them
        await mlp_main.main()
        second = await _fetch('mx1:25CF61E7BCF')
        return first, second

    (doc, count, indexes, by_host), (doc2, count2, _, _) = asyncio.run(run())
    assert count == 10 and count2 == 10
    assert 'host' in indexes
    assert by_host == 1

    assert doc['id'] == 'mx1:25CF61E7BCF'
    assert doc['host'] == 'mx1'
    assert doc['client'] == {'host': 'unknown', 'ip': '192.168.140.50'}
    assert doc['sasl_method'] == 'login' and doc['sasl_username'] == 'dms@example.com'
    assert doc['service'] == 'submission'
    assert doc['relay'] == {'host': 'example-com.mail.protection.outlook.com', 'ip': '52.101.91.156', 'port': '25'}
    assert doc['dsn'] == '2.6.0' and doc['delay'] == 1.9 and doc['delays'] == '0.12/0.01/0.37/1.4'
    assert doc['nrcpt'] == 2
    assert doc['dkim'] == {'domain': 'example.com', 'selector': 'default'}
    assert doc['tls'] is True
    assert [r['to'] for r in doc['recipients']] == ['backup@archive.example', 'john.doe@example.com']
    # times are stored as RethinkDB times (millisecond precision, returned as aware datetimes)
    ms = timedelta(milliseconds=1)
    assert abs(doc['timestamp'] - datetime(2026, 10, 26, 6, 28, 47, 155158, tzinfo=timezone.utc)) < ms
    assert abs(doc['recipients'][1]['timestamp'] - datetime(2026, 10, 26, 6, 28, 49, 80848, tzinfo=timezone.utc)) < ms
    assert isinstance(doc['lines'][0]['timestamp'], datetime)
    assert len(doc['lines']) == 7
    assert doc2 == doc


def test_lock_removed_on_error(db, monkeypatch):
    lock = db

    async def boom(*a, **kw):
        raise RuntimeError('import failed')

    monkeypatch.setattr(mlp_main, 'import_log', boom)
    with pytest.raises(RuntimeError):
        asyncio.run(mlp_main.main())
    assert not os.path.exists(lock)
