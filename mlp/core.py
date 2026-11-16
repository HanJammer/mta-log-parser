"""

Copyright::
    +===================================================+
    |                 © 2019 Privex Inc.                |
    |               https://www.privex.io               |
    +===================================================+
    |                                                   |
    |        Postfix Log Parser / Web UI                |
    |                                                   |
    |        Core Developer(s):                         |
    |                                                   |
    |          (+)  Chris (@someguy123) [Privex]        |
    |                                                   |
    +===================================================+

"""
import asyncio
from contextvars import ContextVar
import json
import logging
import rethinkdb.ast
import rethinkdb.query

from typing import Tuple, List, Union

from privex.helpers import empty
from quart import request
# from quart.exceptions import BadRequest
from werkzeug.exceptions import BadRequest
from rethinkdb import RethinkDB
from rethinkdb.errors import ReqlDriverError
from rethinkdb.ast import DB
from rethinkdb.net import DefaultConnection

from mlp import settings
from privex.loghelper import LogHelper

from mlp.settings import AppError, DEFAULT_ERR, ERRORS

_lh = LogHelper('mlp')
_lh.add_console_handler(level=logging.INFO)

log = logging.getLogger(__name__)

__STORE = {}


# Indexes the web API relies on, created in addition to ``settings.rethink_tables``.
EXTRA_INDEXES = {'sent_mail': ['host', 'service', 'queue_id', 'subject', 'size']}


# Connections are bound to the current asyncio context: each web request (one task per request) uses its own
# connection, released in ``teardown_request``; tasks started from a context that already holds one (``asyncio.gather``
# in the importer) share it. One shared process-wide connection broke every in-flight query whenever a single request
# was cancelled (client went away, client-side timeout) or failed with a driver error.
# Cleanly released connections go back to a small idle pool; a connection that saw a cancellation, a timeout or a
# driver error is closed instead of being reused.
POOL_MAX_IDLE = 8


class _Lease:
    __slots__ = ('db', 'conn', 'r', 'loop', 'dbname', 'dirty')

    def __init__(self, db, conn, r, loop, dbname):
        self.db, self.conn, self.r, self.loop, self.dbname = db, conn, r, loop, dbname
        self.dirty = False


_CONN: ContextVar = ContextVar('mlp_rethink_conn', default=None)
_IDLE: List[_Lease] = []


def mark_dirty():
    """Flag the connection of the current context so it is closed instead of pooled when released."""
    lease = _CONN.get()
    if lease is not None:
        lease.dirty = True


async def close_rethink(discard: bool = False):
    """Release the connection of the current context (end of a web request or of an import run)."""
    lease = _CONN.get()
    _CONN.set(None)
    if lease is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover
        loop = None
    if (not discard and not lease.dirty and lease.loop is loop and lease.conn.is_open()
            and _idle_connection(lease.conn) and len(_IDLE) < POOL_MAX_IDLE):
        _IDLE.append(lease)
        return
    await _quiet(lease.conn.close(noreply_wait=False))


def _idle_connection(conn) -> bool:
    """True when the connection has no query waiting for a response and no open cursor (safe to hand over)."""
    inst = getattr(conn, '_instance', None)
    if inst is None:
        return False
    return not getattr(inst, '_user_queries', True) and not getattr(inst, '_cursor_cache', True)


def _close_lease(lease: '_Lease'):
    try:
        closing = lease.conn.close(noreply_wait=False)
    except Exception:  # pragma: no cover - best effort, the connection may be broken already
        return
    if not asyncio.iscoroutine(closing):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop is lease.loop:
        loop.create_task(_quiet(closing))
    else:
        closing.close()     # the connection's loop is gone; nothing left to close


def reset_rethink():
    """Drop the connection of the current context (e.g. after a connection error); the next call reconnects."""
    lease = _CONN.get()
    _CONN.set(None)
    if lease is not None:
        _close_lease(lease)


def clear_pool():
    """Close all idle pooled connections (tests switch databases and event loops)."""
    while _IDLE:
        _close_lease(_IDLE.pop())


async def _quiet(aw):
    try:
        await aw
    except Exception:  # pragma: no cover
        pass


async def get_rethink() -> Tuple[DB, DefaultConnection, RethinkDB]:
    """

    Usage:

        >>> from mlp.core import get_rethink
        >>>
        >>> r, conn, rDB = await get_rethink()
        >>> r.table('blocks').insert(dict(block_num=1234)).run(conn, array_limit=settings.rethink_arr_limit)


    The connection belongs to the current asyncio context (see ``_CONN``); it is taken from the idle pool or
    opened, and re-created when it was closed.

    :return DB rethink: (Tuple Param 1) - Main RethinkDB database query object :class:`rethinkdb.RethinkDB`
    :return DefaultConnection conn: (Tuple Param 2) - Rethink Connection Object :class:`rethinkdb.net.DefaultConnection`
    """
    loop = asyncio.get_running_loop()
    lease = _CONN.get()
    if lease is not None:
        if lease.loop is loop and lease.conn.is_open() and lease.dbname == settings.rethink_db:
            return lease.db, lease.conn, lease.r
        reset_rethink()

    while _IDLE:
        cand = _IDLE.pop()
        if cand.loop is loop and cand.conn.is_open() and cand.dbname == settings.rethink_db:
            cand.dirty = False
            _CONN.set(cand)
            return cand.db, cand.conn, cand.r
        _close_lease(cand)

    # Setup RethinkDB connection
    r: rethinkdb.query = RethinkDB()
    r.set_loop_type('asyncio')
    conn_kwargs = {}
    if settings.rethink_user:
        conn_kwargs = dict(user=settings.rethink_user, password=settings.rethink_password)
    conn = await r.connect(settings.rethink_host, settings.rethink_port, **conn_kwargs)
    db = r.db(settings.rethink_db)   # type: DB
    if __STORE.get('schema_ready') != settings.rethink_db:
        try:
            await _ensure_schema(r, conn)
        except BaseException:
            await _quiet(conn.close(noreply_wait=False))
            raise
        __STORE['schema_ready'] = settings.rethink_db

    _CONN.set(_Lease(db, conn, r, loop, settings.rethink_db))
    return db, conn, r


async def _ensure_schema(r, conn):
    """Create the database, tables and indexes if missing (once per process)."""
    dbs = await r.db_list().run(conn, array_limit=settings.rethink_arr_limit)
    if settings.rethink_db not in dbs:
        log.debug('Database %s did not exist. Creating.', settings.rethink_db)
        await r.db_create(settings.rethink_db).run(conn, array_limit=settings.rethink_arr_limit)

    # Create required tables inside of database
    db = r.db(settings.rethink_db)   # type: DB
    rtables = await db.table_list().run(conn, array_limit=settings.rethink_arr_limit)
    for t, t2, indexes in settings.rethink_tables:
        if t not in rtables:
            log.debug('Table %s did not exist. Creating.', t)
            await db.table_create(t).run(conn, array_limit=settings.rethink_arr_limit)
        if t2 not in rtables:
            log.debug('Table %s did not exist. Creating.', t2)
            await db.table_create(t2).run(conn, array_limit=settings.rethink_arr_limit)
        idxs = await db.table(t).index_list().run(conn, array_limit=settings.rethink_arr_limit)
        wanted = list(indexes) + [i for i in EXTRA_INDEXES.get(t, []) if i not in indexes]
        created = []
        for index in wanted:
            if index not in idxs:
                log.debug('Index %s on table %s did not exist. Creating.', index, t)
                if index == 'status_code':
                    await db.table(t).index_create(index, r.row['status']['code'], multi=True).run(conn, array_limit=settings.rethink_arr_limit)
                else:
                    await db.table(t).index_create(index).run(conn, array_limit=settings.rethink_arr_limit)
                created.append(index)
        if created:
            await db.table(t).index_wait(*created).run(conn, array_limit=settings.rethink_arr_limit)


async def run(query, conn, timeout: float = None, **kwargs):
    """
    Run a ReQL query with ``array_limit`` from the settings and a client-side timeout
    (``QUERY_TIMEOUT``; raises :class:`asyncio.TimeoutError`). Cursors are drained into a list.
    """
    kwargs.setdefault('array_limit', settings.rethink_arr_limit)
    timeout = settings.query_timeout if timeout is None else timeout

    async def _run():
        res = await query.run(conn, **kwargs)
        if hasattr(res, '__aiter__'):
            out = []
            async for x in res:
                out.append(x)
            return out
        return res

    try:
        if timeout and timeout > 0:
            return await asyncio.wait_for(_run(), timeout)
        return await _run()
    except (asyncio.CancelledError, asyncio.TimeoutError, ReqlDriverError):
        mark_dirty()     # the connection may be mid-response: never hand it to another request
        raise


async def extract_json(rq: request) -> Union[list, dict]:
    """
    Extract JSON formatted POST data from a Quart request.

    **Example** (Dictionary JSON POST data)::

        >>> async def my_view():
        ...     data = extract_json(request)
        ...     if not isinstance(data, dict):
        ...         return jsonify(error=True, message=f"JSON POST data must be a dictionary (map/object)!"), 400
        ...     first_name = data.get('first_name')
        ...     last_name = data.get('last_name')

    **Example** (List JSON POST data)::

        >>> async def other_view():
        ...     data = extract_json(request)
        ...     if not isinstance(data, list):
        ...         return jsonify(error=True, message=f"JSON POST data must be a list (array)!"), 400
        ...     for name in data:

    """
    try:
        data = await rq.get_json(force=True)
        return data
    except (json.decoder.JSONDecodeError, BadRequest) as e:
        log.debug('get_json failed, falling back to extracting from form keys')
        data = list(rq.form.keys())
        if len(data) >= 1:
            return json.loads(data[0])
        raise e


def get_accepts(headers) -> List[str]:
    lower_headers = {k.lower(): v for k, v in headers.items()}
    accepts = lower_headers.get('accept', 'application/json').split(',')
    return [a.split(';')[0] for a in accepts]


async def filter_methods(data: list):
    methods = {}
    for d in data:
        m = d['method']
        if m not in methods:
            methods[m] = []
        methods[m].append(d)
    return methods


def _get_error(code: str, fallback: str = 'UNKNOWN_ERROR') -> AppError:
    """
    Attempt to retrieve an :class:`.AppError` by it's error code, with fallback to the error code ``fallback``.

    If something goes wrong trying to fallback to ``fallback``, then :attr:`.DEFAULT_ERR` will be returned instead.

        >>> err = _get_error('NOT_FOUND')
        >>> print(err.code, err.message)
        NOT_FOUND The requested resource or URL was not found. You may wish to check the URL for typos.

        >>> err = _get_error('NON_EXISTENT_ERR')
        >>> print(err.code, err.message)
        UNKNOWN_ERROR An unknown error has occurred. Please contact the administrator of this site.

    :param str code:      The error code to attempt to retrieve, e.g. ``NOT_FOUND``.
    :param str fallback:  The error code to attempt to fallback to, if ``code`` wasn't found.
    :return AppError err: An instance of an error in :class:`.AppError` form.
    """
    e = ERRORS.get(code, ERRORS.get(fallback))
    if empty(e, True, True): return DEFAULT_ERR
    return e


def add_app_error(code: str, msg: str, status: int = 500) -> AppError:
    """
    Add a new error code for easy API error raising.

        >>> add_app_error("INV_TOKEN", "Invalid API token specified in Authorization header.", 403)


    :param str code:     A short, unique capitalized error code, e.g. ``INV_USERNAME`` - this code should be static, i.e. never change,
                         since it should be used by API clients for handling certain errors.
    :param str msg:      A human readable error message, e.g. "Username must be at least 5 characters"
    :param int status:   An integer HTTP status code that should be returned when this error is raised.
    :return AppError err:  The :class:`.AppError` instance which was added/updated in :attr:`.ERRORS`
    """
    ERRORS[code] = AppError(code, msg, status)
    return ERRORS[code]

