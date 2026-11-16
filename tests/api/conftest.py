"""
Fixtures for the web API tests. They run the Quart test client against a real RethinkDB
(``RETHINK_HOST``/``RETHINK_PORT``, default localhost:28015) in the database ``mlp_test_api``,
which is dropped at the end of the session.
"""
import os

import pytest
import pytest_asyncio

TEST_DB = os.environ.get('MLP_TEST_API_DB', 'mlp_test_api')
TEST_SECRET = 'test-secret-key-for-the-api-tests-0123456789'

from mlp import settings  # noqa: E402
from mlp import auth, core  # noqa: E402

# Importing mlp.webui builds the default app, which resolves the secret key: use the test key so no
# instance/secret_key file is generated in the repository.
_orig_secret = settings.secret_key
settings.secret_key = TEST_SECRET
from mlp.webui import create_app  # noqa: E402
settings.secret_key = _orig_secret

from api.api_helpers import CSRF, FIXTURE_DOCS, login, post  # noqa: E402,F401

# 'localhost' may resolve to ::1 first (slow on Windows when RethinkDB listens on IPv4 only)
TEST_HOST = '127.0.0.1' if settings.rethink_host == 'localhost' else settings.rethink_host


@pytest.fixture(autouse=True)
def _api_settings(monkeypatch):
    """Point the shared settings at the API test database (other test suites use their own DB)."""
    core.reset_rethink()
    core.clear_pool()
    monkeypatch.setattr(settings, 'rethink_db', TEST_DB)
    monkeypatch.setattr(settings, 'rethink_host', TEST_HOST)
    monkeypatch.setattr(settings, 'secret_key', TEST_SECRET)
    monkeypatch.setattr(settings, 'query_timeout', 30)
    monkeypatch.setattr(settings, 'ldap_connect', '')
    yield
    core.reset_rethink()
    core.clear_pool()


@pytest.fixture(scope='session', autouse=True)
def _drop_test_db():
    yield
    from rethinkdb import RethinkDB
    r = RethinkDB()
    try:
        with r.connect(TEST_HOST, settings.rethink_port) as conn:
            if TEST_DB in r.db_list().run(conn):
                r.db_drop(TEST_DB).run(conn)
    except Exception:  # pragma: no cover
        pass


@pytest_asyncio.fixture
async def db():
    """Clean tables with the fixture documents loaded. Yields ``(db, conn)``."""
    d, conn, _ = await core.get_rethink()
    await d.table('auth').delete().run(conn)
    await d.table('sent_mail').delete().run(conn)
    await d.table('sent_mail').insert(FIXTURE_DOCS).run(conn)
    yield d, conn
    core.reset_rethink()
    core.clear_pool()


@pytest.fixture
def make_app():
    def _make(prefix: str = ''):
        return create_app(path_prefix=prefix, secret_key=TEST_SECRET)
    return _make


@pytest_asyncio.fixture
async def app(db, make_app):
    return make_app('')


@pytest_asyncio.fixture
async def client(app):
    return app.test_client()


@pytest_asyncio.fixture
async def user(db):
    await auth.create_user('admin', 'password123')
    return 'admin'


@pytest_asyncio.fixture
async def authed(client, user):
    res = await login(client)
    assert res.status_code == 200, await res.get_data(as_text=True)
    return client
