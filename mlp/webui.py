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

Quart application factory. The JSON API and the SPA shell live in :mod:`mlp.views`.
"""
import asyncio
import logging
from datetime import timedelta

from quart import Quart, request
from rethinkdb.errors import ReqlAvailabilityError, ReqlDriverError, ReqlError, ReqlResourceLimitError
from werkzeug.exceptions import HTTPException

from mlp import api, settings
from mlp.core import close_rethink, reset_rethink
from mlp.exceptions import APIException
from mlp.queries import FilterError
from mlp.security import SECURITY_HEADERS, SPA_CSP, LoginThrottle, resolve_secret_key
from mlp.views import bp, STATIC_DIR

log = logging.getLogger(__name__)

ASSET_MAX_AGE = 365 * 24 * 3600


def normalize_prefix(prefix: str) -> str:
    prefix = (prefix or '').strip().rstrip('/')
    if prefix and not prefix.startswith('/'):
        prefix = '/' + prefix
    return prefix


def create_app(path_prefix: str = None, secret_key: str = None) -> Quart:
    prefix = normalize_prefix(settings.path_prefix if path_prefix is None else path_prefix)

    app = Quart(__name__, static_folder=STATIC_DIR, static_url_path=prefix + '/static')
    app.json = api.MLPJSONProvider(app)
    app.secret_key = secret_key or resolve_secret_key()
    app.config.update(
        DEBUG=settings.DEBUG,
        MLP_PATH_PREFIX=prefix,
        SESSION_COOKIE_NAME='mlp_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
        SESSION_COOKIE_PATH=(prefix or '') + '/',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=max(settings.session_lifetime_hours, 1)),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.extensions['mlp_login_throttle'] = LoginThrottle()
    app.register_blueprint(bp, url_prefix=prefix or None)

    assets_path = prefix + '/static/app/assets/'

    @app.after_request
    async def _headers(resp):
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        resp.headers.setdefault('Content-Security-Policy', SPA_CSP)
        if request.path.startswith(assets_path) and resp.status_code == 200:
            resp.headers['Cache-Control'] = f'public, max-age={ASSET_MAX_AGE}, immutable'
        elif request.path.startswith(prefix + '/api'):
            resp.headers.setdefault('Cache-Control', 'no-store')
        return resp

    @app.teardown_request
    async def _close_db(exc=None):
        # every request has its own RethinkDB connection (see mlp.core._CONN)
        await close_rethink()

    @app.errorhandler(FilterError)
    async def _filter_error(exc: FilterError):
        return api.error(exc.error_code, exc.message, 400)

    @app.errorhandler(APIException)
    async def _api_exception(exc: APIException):
        return api.error(exc.error_code, exc.message or str(exc), exc.status or 500)

    @app.errorhandler(HTTPException)
    async def _http_error(exc: HTTPException):
        code = exc.code or 500
        name = {404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED', 413: 'TOO_LARGE'}.get(code, 'HTTP_ERROR')
        return api.error(name, exc.description or exc.name, code)

    @app.errorhandler(asyncio.TimeoutError)
    async def _timeout(exc):
        log.warning('Query timed out after %ss: %s', settings.query_timeout, request.full_path)
        return api.error('QUERY_TIMEOUT', 'The query took too long. Narrow the time window or the filters.', 504)

    @app.errorhandler(ReqlError)
    async def _rethink_error(exc: ReqlError):
        if isinstance(exc, (ReqlDriverError, ReqlAvailabilityError)):
            log.error('RethinkDB unavailable: %s', exc)
            reset_rethink()
            return api.error('DB_UNAVAILABLE', 'The database is not reachable.', 503)
        if isinstance(exc, ReqlResourceLimitError):
            log.warning('RethinkDB resource limit: %s', exc)
            return api.error('RESULT_TOO_LARGE', 'The result is too large (RETHINK_ARR_LIMIT). Narrow the filters.', 400)
        log.exception('RethinkDB query error')
        return api.error('DB_ERROR', 'Database query failed.', 500)

    @app.errorhandler(Exception)
    async def _unknown(exc: Exception):
        # Never expose tracebacks to clients, not even with DEBUG; they go to the server log.
        log.exception('Unhandled error on %s %s', request.method, request.path)
        return api.error('UNKNOWN_ERROR', 'An unknown error has occurred.', 500)

    return app


app = create_app()
