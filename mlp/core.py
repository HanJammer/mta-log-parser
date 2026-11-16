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


# The connection belongs to the current asyncio context: each web request (one task per request) gets its own
# connection, closed in ``teardown_request``; tasks started from a context that already has one (``asyncio.gather``
# in the importer) share it. One shared process-wide connection broke every in-flight query whenever one request
# was cancelled (client went away, client-side timeout) or failed with a driver error.
_CONN: ContextVar = ContextVar('mlp_rethink_conn', default=None)


async def close_rethink():
    """Close the connection of the current context (end of a web request, end of an import run)."""
    cached = _CONN.get()
    _CONN.set(None)
    if cached is not None:
        await _quiet(cached[1].close(noreply_wait=False))


def reset_rethink():
    """Forget the connection of the current context (e.g. after a connection error) and close it; the next call reconnects."""
    cached = _CONN.get()
    _CONN.set(None)
    cached_loop = cached[3] if cached is not None else None
    if cached is None:
        return
    try:
        closing = cached[1].close(noreply_wait=False)
    except Exception:  # pragma: no cover - best effort, the connection may be broken already
        return
    if not asyncio.iscoroutine(closing):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop is cached_loop:
        loop.create_task(_quiet(closing))
    else:
        closing.close()     # the connection's loop is gone; nothing left to close


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


    The connection is cached per asyncio context (see ``_CONN``) and re-created when it was closed.

    :return DB rethink: (Tuple Param 1) - Main RethinkDB database query object :class:`rethinkdb.RethinkDB`
    :return DefaultConnection conn: (Tuple Param 2) - Rethink Connection Object :class:`rethinkdb.net.DefaultConnection`
    """
    loop = asyncio.get_running_loop()
    cached = _CONN.get()
    if cached is not None:
        if cached[3] is loop and cached[1].is_open():
            return cached[:3]
        reset_rethink()

    # Setup RethinkDB connection
    # log.debug('Initialising RethinkDB connector')
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

    _CONN.set((db, conn, r, loop))
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

    if timeout and timeout > 0:
        return await asyncio.wait_for(_run(), timeout)
    return await _run()


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

