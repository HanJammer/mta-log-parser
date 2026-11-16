"""
HTTP endpoints of MTA Log Parser 2.0: the JSON API (``/api/*``) and the single-page app shell.

The blueprint is registered under ``PATH_PREFIX`` by :func:`mlp.webui.create_app`.
See ``docs/DESIGN-v2.md`` ("HTTP API") for the contract.
"""
import html
import logging
import os
import time
from functools import wraps
from typing import Optional

from quart import Blueprint, Response, current_app, g, jsonify, request, session
from rethinkdb import r

from mlp import api, auth, settings, stats
from mlp.core import get_rethink, run
from mlp.queries import FilterError, apply_filters, parse_filters, parse_order
from mlp.security import csrf_ok

log = logging.getLogger(__name__)

bp = Blueprint('mlp', __name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
SPA_INDEX = os.path.join(STATIC_DIR, 'app', 'index.html')
PREFIX_PLACEHOLDER = '__MLP_PREFIX__'
EMAILS_TABLE = 'sent_mail'


def _version() -> str:
    try:
        from mlp.main import VERSION
        return VERSION
    except Exception:  # pragma: no cover - the parser module is optional for the web app
        return 'unknown'


def _lockfile() -> str:
    try:
        from mlp.main import lockfile
        return lockfile
    except Exception:  # pragma: no cover
        return 'processing.lock'


def _prefix() -> str:
    return current_app.config.get('MLP_PATH_PREFIX', '')


def _throttle():
    return current_app.extensions['mlp_login_throttle']


async def _json_body() -> dict:
    data = await request.get_json(silent=True)
    if not isinstance(data, dict):
        raise FilterError('Request body must be a JSON object.', 'INVALID_BODY')
    return data


def _str_field(body: dict, name: str) -> str:
    v = body.get(name)
    if not isinstance(v, str) or v == '':
        raise FilterError(f'Field {name!r} is required (non-empty string).', 'INVALID_BODY')
    return v


# --- session handling --------------------------------------------------------------------------

def _session_lifetime() -> int:
    return max(settings.session_lifetime_hours, 1) * 3600


async def current_login() -> Optional[str]:
    """
    Login of the authenticated user, or None. The session is dropped when it expired, the auth
    mode changed, or (local accounts) the account was deleted or its password changed.
    """
    if 'mlp_login' in g:
        return g.mlp_login
    login = session.get('login')
    mode = session.get('auth')
    iat = session.get('iat')
    result = None
    if login and mode == auth.auth_mode() and isinstance(iat, (int, float)) and 0 <= time.time() - iat <= _session_lifetime():
        if mode == 'local':
            row = await auth.get_user(login)
            if row is not None and auth.password_version(row) == session.get('pwv'):
                result = login
        else:
            result = login          # LDAP is only asked at login; afterwards the session expiry applies
    if result is None and session:
        session.clear()
    g.mlp_login = result
    return result


def _start_session(login: str, row: dict = None):
    session.clear()
    session.permanent = True
    session['login'] = login
    session['auth'] = auth.auth_mode()
    session['iat'] = int(time.time())
    if row is not None:
        session['pwv'] = auth.password_version(row)
    g.mlp_login = login


def login_required(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        if await current_login() is None:
            return api.error('UNAUTHORIZED', 'Authentication required.', 401)
        return await f(*args, **kwargs)
    return wrapper


def local_auth_only(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        if auth.auth_mode() != 'local':
            return api.error('LOCAL_AUTH_ONLY', 'Accounts are managed in LDAP.', 400)
        return await f(*args, **kwargs)
    return wrapper


@bp.before_request
async def _csrf_guard():
    if not csrf_ok(request.method, request.headers, request.mimetype):
        return api.error('CSRF_FAILED', 'State-changing requests need "Content-Type: application/json" and '
                                        '"X-Requested-With: mlp".', 403)


# --- session & accounts ------------------------------------------------------------------------

@bp.route('/api/session', methods=['GET'])
async def api_session():
    login = await current_login()
    mode = auth.auth_mode()
    needs_setup = mode == 'local' and await auth.count_users() == 0
    data = {
        'authenticated': login is not None,
        'login': login,
        'auth_mode': mode,
        'needs_setup': needs_setup,
        'version': _version(),
        'config': {'mail_domain': settings.mail_domain},
    }
    if login is not None:
        data['config'].update({
            'mta': settings.mta or 'postfix',
            'default_limit': settings.default_limit,
            'max_limit': settings.max_limit,
            'housekeeping_days': settings.housekeeping_days or None,
            'datetime_format': settings.datetime_format,
            'gui_max_log_period': settings.gui_max_log_period,
            'exclude_from_top_senders': [x.strip() for x in settings.exclude_from_top_senders.split(',') if x.strip()],
            'exclude_from_top_recipients': [x.strip() for x in settings.exclude_from_top_recipients.split(',') if x.strip()],
        })
    return jsonify(data)


@bp.route('/api/login', methods=['POST'])
async def api_login():
    body = await _json_body()
    login, password = _str_field(body, 'login'), _str_field(body, 'password')
    if len(login) > 256 or len(password) > auth.PASSWORD_MAX_LEN:
        return api.error('INVALID_CREDENTIALS', 'Invalid login or password.', 401)

    ip = request.remote_addr or ''
    wait = _throttle().retry_after(ip, login)
    if wait:
        return api.error('TOO_MANY_ATTEMPTS', 'Too many failed logins. Try again later.', 429,
                         headers={'Retry-After': str(wait)})
    row = None
    try:
        if auth.auth_mode() == 'local':
            row = await auth.authenticate_local(login, password)
            ok = row is not None
        else:
            ok = await auth.authenticate_ldap(login, password)
    except auth.AuthError as e:
        return api.error(e.error_code, e.message, e.status)

    if not ok:
        _throttle().failure(ip, login)
        log.warning('Failed login for %r from %s', login, ip)
        return api.error('INVALID_CREDENTIALS', 'Invalid login or password.', 401)

    _throttle().success(ip, login)
    login = row['id'] if row is not None else login
    _start_session(login, row)
    log.info('Login of %r from %s', login, ip)
    return jsonify({'login': login})


@bp.route('/api/logout', methods=['POST'])
async def api_logout():
    session.clear()
    return Response('', status=204)


@bp.route('/api/setup', methods=['POST'])
@local_auth_only
async def api_setup():
    if await auth.count_users() > 0:
        return api.error('ALREADY_SET_UP', 'An account already exists.', 409)
    body = await _json_body()
    err = auth.validate_login(body.get('login')) or auth.validate_password(body.get('password'))
    if err:
        return api.error('INVALID_ACCOUNT', err, 400)
    if not await auth.create_user(body['login'], body['password']):
        return api.error('ALREADY_SET_UP', 'An account already exists.', 409)
    _start_session(body['login'], await auth.get_user(body['login']))
    log.info('First account %r created from %s', body['login'], request.remote_addr)
    return jsonify({'login': body['login']}), 201


@bp.route('/api/users', methods=['GET'])
@login_required
@local_auth_only
async def api_users():
    return jsonify(await auth.list_users())


@bp.route('/api/users', methods=['POST'])
@login_required
@local_auth_only
async def api_users_create():
    body = await _json_body()
    err = auth.validate_login(body.get('login')) or auth.validate_password(body.get('password'))
    if err:
        return api.error('INVALID_ACCOUNT', err, 400)
    if not await auth.create_user(body['login'], body['password']):
        return api.error('USER_EXISTS', 'An account with this login already exists.', 409)
    log.info('Account %r created by %r', body['login'], g.mlp_login)
    return jsonify({'login': body['login']}), 201


@bp.route('/api/users/<login>', methods=['PUT'])
@login_required
@local_auth_only
async def api_users_update(login):
    body = await _json_body()
    err = auth.validate_password(body.get('password'))
    if err:
        return api.error('INVALID_ACCOUNT', err, 400)
    row = await auth.set_password(login, body['password'])
    if row is None:
        return api.error('NOT_FOUND', 'No such account.', 404)
    if login == g.mlp_login:
        session['pwv'] = auth.password_version(row)     # keep the own session, drop the others
    log.info('Password of account %r changed by %r', login, g.mlp_login)
    return jsonify({'login': login})


@bp.route('/api/users/<login>', methods=['DELETE'])
@login_required
@local_auth_only
async def api_users_delete(login):
    if await auth.get_user(login) is None:
        return api.error('NOT_FOUND', 'No such account.', 404)
    if await auth.count_users() <= 1:
        return api.error('LAST_ACCOUNT', 'The last account cannot be deleted.', 409)
    await auth.delete_user(login)
    log.info('Account %r deleted by %r', login, g.mlp_login)
    if login == g.mlp_login:
        session.clear()
    return Response('', status=204)


# --- emails ------------------------------------------------------------------------------------

async def _emails_table():
    db, conn, _ = await get_rethink()
    table = db.table(EMAILS_TABLE)
    indexes = set(await run(table.index_list(), conn)) | {'id'}
    return table, conn, indexes


def _int_arg(name: str, default: int) -> int:
    v = request.args.get(name)
    if v in (None, ''):
        return default
    try:
        return int(v)
    except ValueError:
        raise FilterError(f'{name} must be an integer.', 'INVALID_PARAMETER')


def _ordered_page_query(table, flt, indexes, order: str, order_dir: str):
    """Filtered query in the requested order; ordering goes through the field's index."""
    if order in indexes:
        idx = r.desc(order) if order_dir == 'desc' else order
        if order in flt.ranges:
            lo, hi = flt.ranges[order]
            q = table.between(r.minval if lo is None else lo, r.maxval if hi is None else hi,
                              index=order, left_bound='closed', right_bound='closed').order_by(index=idx)
            pred = flt.row_predicate(skip_range=order)
        else:
            q = table.order_by(index=idx)
            pred = flt.row_predicate()
        return q.filter(pred) if pred is not None else q
    # Only reachable if an index is missing: order in memory (bounded by RETHINK_ARR_LIMIT).
    q, _ = apply_filters(table, flt, indexes)
    key = (lambda row: row[order].default(None))
    return q.order_by(r.desc(key) if order_dir == 'desc' else key)


@bp.route('/api/emails', methods=['GET'])
@bp.route('/api/emails/', methods=['GET'])
@login_required
async def api_emails():
    """
    List of messages (without ``lines``). See :mod:`mlp.queries` for the filter syntax, e.g.::

        /api/emails?status.code__eq=sent,deferred&host__eq=mx1&mail_to=example.com&timestamp__gt=2026-10-26T00:00:00Z
    """
    args = request.args
    flt = parse_filters(args)
    order, order_dir = parse_order(args)
    limit = _int_arg('limit', settings.default_limit)
    limit = settings.default_limit if limit <= 0 else min(limit, settings.max_limit)
    page = _int_arg('page', 0)
    offset = limit * (page - 1) if page > 0 else max(_int_arg('offset', 0), 0)

    table, conn, indexes = await _emails_table()
    count_q, _ = apply_filters(table, flt, indexes)
    count = await run(count_q.count(), conn)

    # Past the end: clamp to the last page like 1.x did.
    if offset >= count:
        offset = max(count - 1, 0) // limit * limit
    total_pages = max((count + limit - 1) // limit, 1)

    q = _ordered_page_query(table, flt, indexes, order, order_dir)
    docs = await run(q.skip(offset).limit(limit).without('lines'), conn)
    return jsonify({
        'error': False, 'result': docs, 'count': count, 'remaining': max(count - offset, 0),
        'page': offset // limit + 1, 'total_pages': total_pages,
    })


@bp.route('/api/emails/<path:email_id>', methods=['GET'])
@login_required
async def api_email(email_id):
    db, conn, _ = await get_rethink()
    if len(email_id) > 512:
        return api.error('NOT_FOUND', 'No message with this id.', 404)
    doc = await run(db.table(EMAILS_TABLE).get(email_id), conn)
    if doc is None:
        return api.error('NOT_FOUND', 'No message with this id.', 404)
    return jsonify(doc)


@bp.route('/api/facets', methods=['GET'])
@login_required
async def api_facets():
    table, conn, indexes = await _emails_table()

    async def distinct(index, getter):
        if index in indexes:
            vals = await run(table.distinct(index=index), conn)
        else:  # pragma: no cover - indexes are created at startup
            vals = await run(table.map(getter).distinct(), conn)
        return sorted(v for v in vals if isinstance(v, str) and v != '')

    return jsonify({
        'hosts': await distinct('host', lambda row: row['host'].default('')),
        'statuses': await distinct('status_code', lambda row: row['status']['code'].default('')),
        'services': await distinct('service', lambda row: row['service'].default('')),
    })


@bp.route('/api/stats', methods=['GET'])
@login_required
async def api_stats():
    args = request.args
    flt = parse_filters(args, ignore=stats.STATS_PARAMS)
    table, conn, indexes = await _emails_table()
    if 'statuses' in args:
        return jsonify(await stats.status_count(table, conn, flt, indexes, str(args.get('statuses'))))
    for mode, fn in (('top_senders', stats.top_senders), ('top_recipients', stats.top_recipients),
                     ('top_relays', stats.top_relays), ('by_host', stats.by_host), ('timeline', stats.timeline)):
        if mode in args:
            return jsonify(await fn(table, conn, flt, indexes, args))
    return api.error('INVALID_STATS_MODE', 'Use one of: statuses, top_senders, top_recipients, top_relays, '
                                           'by_host, timeline.', 400)


@bp.route('/api/process_check', methods=['GET'])
@bp.route('/api/process_check/', methods=['GET'])
async def process_check():
    """Unauthenticated on purpose (unchanged from 1.x): only says whether the importer is running."""
    if settings.gui_refresh_block:
        return {'processing': os.path.isfile(_lockfile())}
    return {'processing': False}


@bp.route('/api', methods=['GET', 'POST', 'PUT', 'DELETE'])
@bp.route('/api/<path:rest>', methods=['GET', 'POST', 'PUT', 'DELETE'])
async def api_not_found(rest=None):
    return api.error('NOT_FOUND', 'Unknown API endpoint.', 404)


# --- single-page app ---------------------------------------------------------------------------

def render_spa_index(prefix: str) -> Optional[str]:
    """``index.html`` of the SPA build with ``__MLP_PREFIX__`` replaced and the ``mlp-prefix`` meta tag injected."""
    try:
        with open(SPA_INDEX, 'r', encoding='utf-8') as fh:
            page = fh.read()
    except FileNotFoundError:
        return None
    page = page.replace(PREFIX_PLACEHOLDER, prefix)
    meta = f'<meta name="mlp-prefix" content="{html.escape(prefix, quote=True)}">'
    pos = page.lower().find('</head>')
    if pos >= 0:
        return page[:pos] + '    ' + meta + '\n' + page[pos:]
    return meta + page


@bp.route('/', methods=['GET'])
@bp.route('/<path:client_route>', methods=['GET'])
async def spa(client_route: str = ''):
    if client_route == 'static' or client_route.startswith('static/'):
        return api.error('NOT_FOUND', 'File not found.', 404)
    page = render_spa_index(_prefix())
    if page is None:
        return Response('The web UI is not built (mlp/static/app/index.html is missing).', status=503,
                        mimetype='text/plain')
    resp = Response(page, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp
