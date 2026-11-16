"""
Authentication: local accounts (table ``auth``, hashed passwords) and optional LDAP.

Local account rows look like ``{"id": <login>, "password_hash": <werkzeug hash>}``. Rows written by
1.x hold a plaintext ``password`` field; they keep working and are upgraded to a hash on the first
successful login.

``python-ldap`` is imported lazily, only when ``LDAP_CONNECT`` is configured, so the app runs without it.
"""
import asyncio
import hashlib
import hmac
import logging
import re
from typing import List, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from mlp import settings
from mlp.core import get_rethink

log = logging.getLogger(__name__)

AUTH_TABLE = 'auth'

LOGIN_RE = re.compile(r'^[A-Za-z0-9._@-]{3,64}$')
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 1024

# Used to spend the same time on unknown logins as on known ones.
_DUMMY_HASH = generate_password_hash('not-a-real-password-' + 'x' * 16)


class AuthError(Exception):
    """Authentication failed for a reason that should be shown as a specific error code."""

    def __init__(self, error_code: str, message: str, status: int = 401):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status = status


def auth_mode() -> str:
    return 'ldap' if settings.ldap_connect else 'local'


def validate_login(login) -> Optional[str]:
    """Return an error message if ``login`` is not an acceptable new account name."""
    if not isinstance(login, str) or not LOGIN_RE.match(login):
        return 'Login must be 3-64 characters: letters, digits, ".", "_", "@" or "-".'
    return None


def validate_password(password) -> Optional[str]:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LEN:
        return f'Password must be at least {PASSWORD_MIN_LEN} characters long.'
    if len(password) > PASSWORD_MAX_LEN:
        return f'Password must be at most {PASSWORD_MAX_LEN} characters long.'
    return None


def password_version(row: dict) -> str:
    """Short fingerprint of the stored credential; sessions carry it so a password change logs other sessions out."""
    secret = row.get('password_hash') or row.get('password') or ''
    return hashlib.sha256(('mlp-pwv:' + secret).encode('utf-8')).hexdigest()[:16]


async def _hash(password: str) -> str:
    return await asyncio.to_thread(generate_password_hash, password)


async def _check(pwhash: str, password: str) -> bool:
    return await asyncio.to_thread(check_password_hash, pwhash, password)


# --- local account store -----------------------------------------------------------------------

async def _table():
    r, conn, _ = await get_rethink()
    return r.table(AUTH_TABLE), conn


async def get_user(login: str) -> Optional[dict]:
    if not isinstance(login, str) or not login:
        return None
    tbl, conn = await _table()
    return await tbl.get(login).run(conn)


async def count_users() -> int:
    tbl, conn = await _table()
    return await tbl.count().run(conn)


async def list_users() -> List[dict]:
    tbl, conn = await _table()
    logins = await tbl.pluck('id').order_by('id').run(conn, array_limit=settings.rethink_arr_limit)
    return [{'login': u['id']} for u in logins]


async def create_user(login: str, password: str) -> bool:
    """Create an account. Returns False if the login already exists."""
    tbl, conn = await _table()
    res = await tbl.insert({'id': login, 'password_hash': await _hash(password)}, conflict='error').run(conn)
    return res.get('inserted', 0) == 1


async def set_password(login: str, password: str) -> Optional[dict]:
    """Replace the password of an existing account. Returns the new row, or None if it does not exist."""
    tbl, conn = await _table()
    row = {'id': login, 'password_hash': await _hash(password)}
    if await tbl.get(login).run(conn) is None:
        return None
    await tbl.get(login).replace(row).run(conn)
    return row


async def delete_user(login: str) -> bool:
    tbl, conn = await _table()
    res = await tbl.get(login).delete().run(conn)
    return res.get('deleted', 0) == 1


async def authenticate_local(login: str, password: str) -> Optional[dict]:
    """
    Check a local login. Returns the (possibly upgraded) account row on success, else None.
    Legacy plaintext rows are re-written with a password hash after a successful login.
    """
    row = await get_user(login)
    if row is None:
        await _check(_DUMMY_HASH, password)
        return None
    if row.get('password_hash'):
        return row if await _check(row['password_hash'], password) else None

    legacy = row.get('password')
    if not isinstance(legacy, str) or not legacy:
        await _check(_DUMMY_HASH, password)
        return None
    if not hmac.compare_digest(legacy.encode('utf-8'), password.encode('utf-8')):
        return None
    new_row = {'id': row['id'], 'password_hash': await _hash(password)}
    tbl, conn = await _table()
    await tbl.get(row['id']).replace(new_row).run(conn)
    log.info('Upgraded legacy plaintext password of account %r to a hash.', row['id'])
    return new_row


# --- LDAP --------------------------------------------------------------------------------------

def _import_ldap():
    try:
        import ldap  # noqa
        import ldap.filter  # noqa
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise AuthError('LDAP_UNAVAILABLE', 'LDAP_CONNECT is set but python-ldap is not installed.', 500) from e
    return ldap


def _ldap_err(e) -> str:
    try:
        if e.args and isinstance(e.args[0], dict):
            return str(e.args[0].get('desc', e))
    except Exception:
        pass
    return str(e)


def _ldap_connection(ldap):
    conn = ldap.initialize(settings.ldap_connect)
    conn.protocol_version = settings.ldap_version
    conn.set_option(ldap.OPT_REFERRALS, 0)
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, settings.ldap_timeout)
    conn.set_option(ldap.OPT_TIMEOUT, settings.ldap_timeout)
    return conn


def _ldap_authenticate_sync(login: str, password: str) -> bool:
    """
    Blocking LDAP check: bind as the service account, search for the user with an escaped filter,
    then bind as the user. Returns True on success, False on bad credentials / unknown user.
    """
    ldap = _import_ldap()
    escaped = ldap.filter.escape_filter_chars(login)
    criteria = settings.ldap_searchfilter % (settings.ldap_username_attr, escaped)

    conn = _ldap_connection(ldap)
    try:
        conn.simple_bind_s(settings.ldap_bind_dn, settings.ldap_bind_dn_pwd)
        result = conn.search_s(settings.ldap_searchbase, ldap.SCOPE_SUBTREE, criteria, [settings.ldap_username_attr])
    except ldap.INVALID_CREDENTIALS:
        log.error('LDAP: the service account (LDAP_BIND_DN) credentials are incorrect.')
        raise AuthError('LDAP_BIND_ERROR', 'LDAP service account bind failed.', 500)
    except ldap.LDAPError as e:
        log.error('LDAP search failed: %s', _ldap_err(e))
        raise AuthError('LDAP_ERROR', 'LDAP server error.', 502)
    finally:
        try:
            conn.unbind_s()
        except Exception:
            pass

    # Referrals come back with dn None; exactly one real entry must match.
    entries = [(dn, attrs) for dn, attrs in (result or []) if dn]
    if len(entries) != 1:
        if len(entries) > 1:
            log.warning('LDAP: search for %r returned %d entries - refusing login.', login, len(entries))
        return False

    user_dn = entries[0][0]
    bind_name = f'{login}@{settings.ldap_username_domain_part}' if settings.ldap_username_domain_part else user_dn
    uconn = _ldap_connection(ldap)
    try:
        uconn.simple_bind_s(bind_name, password)
        return True
    except ldap.INVALID_CREDENTIALS:
        return False
    except ldap.LDAPError as e:
        log.error('LDAP user bind failed: %s', _ldap_err(e))
        raise AuthError('LDAP_ERROR', 'LDAP server error.', 502)
    finally:
        try:
            uconn.unbind_s()
        except Exception:
            pass


async def authenticate_ldap(login: str, password: str) -> bool:
    # An empty password would make simple_bind_s an anonymous (unauthenticated) bind that "succeeds".
    if not password or not login or not LOGIN_RE.match(login):
        return False
    return await asyncio.to_thread(_ldap_authenticate_sync, login, password)
