"""Session, setup, login/logout, throttling, CSRF, accounts and other security behaviour."""
import sys
import time
import types

import pytest

from api_helpers import CSRF, login, post
from mlp import auth, security, settings

pytestmark = pytest.mark.asyncio


async def _json(res):
    return await res.get_json()


# --- session / setup ---------------------------------------------------------------------------

async def test_session_anonymous_needs_setup(client, db):
    res = await client.get('/api/session')
    assert res.status_code == 200
    data = await _json(res)
    assert data['authenticated'] is False and data['login'] is None
    assert data['auth_mode'] == 'local' and data['needs_setup'] is True
    assert 'version' in data
    assert set(data['config']) == {'mail_domain'}


async def test_setup_flow(client, db):
    res = await post(client, '/api/setup', {'login': 'first.admin', 'password': 'longenough1'})
    assert res.status_code == 201
    assert (await _json(res)) == {'login': 'first.admin'}
    data = await _json(await client.get('/api/session'))
    assert data['authenticated'] is True and data['login'] == 'first.admin' and data['needs_setup'] is False
    for key in ('mta', 'mail_domain', 'default_limit', 'max_limit', 'housekeeping_days', 'datetime_format',
                'gui_max_log_period', 'exclude_from_top_senders', 'exclude_from_top_recipients'):
        assert key in data['config']
    # second setup refused, even from an anonymous client
    other = client.app.test_client()
    res = await post(other, '/api/setup', {'login': 'intruder', 'password': 'longenough1'})
    assert res.status_code == 409
    assert await auth.get_user('intruder') is None


@pytest.mark.parametrize('body', [
    {'login': 'ab', 'password': 'longenough1'},
    {'login': '<script>x</script>', 'password': 'longenough1'},
    {'login': 'good.name', 'password': 'short'},
    {'login': 'good.name'},
    {'password': 'longenough1'},
])
async def test_setup_validation(client, db, body):
    res = await post(client, '/api/setup', body)
    assert res.status_code == 400
    assert (await _json(res))['error'] is True
    assert await auth.count_users() == 0


async def test_password_is_hashed(client, db):
    await post(client, '/api/setup', {'login': 'admin', 'password': 'password123'})
    row = await auth.get_user('admin')
    assert 'password' not in row
    assert row['password_hash'] != 'password123' and row['password_hash'].startswith(('scrypt:', 'pbkdf2:'))


# --- 401 / 404 / CSRF ------------------------------------------------------------------------

@pytest.mark.parametrize('path', ['/api/emails', '/api/emails/AAA111', '/api/users', '/api/facets',
                                  '/api/stats?statuses=sent', '/api/stats?top_senders=1'])
async def test_unauthenticated_get_is_401_json(client, db, path):
    res = await client.get(path)
    assert res.status_code == 401
    assert 'Location' not in res.headers
    assert (await _json(res)) == {'error': True, 'error_code': 'UNAUTHORIZED', 'message': 'Authentication required.'}


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/users', {'login': 'eve.hacker', 'password': 'password123'}),
    ('PUT', '/api/users/admin', {'password': 'password999'}),
    ('DELETE', '/api/users/admin', None),
])
async def test_unauthenticated_account_management_is_401(client, user, method, path, body):
    res = await post(client, path, body, method=method)
    assert res.status_code == 401
    assert await auth.get_user('eve.hacker') is None
    assert await auth.authenticate_local('admin', 'password123') is not None


async def test_unknown_api_path_is_json_404(client, db):
    res = await client.get('/api/nope')
    assert res.status_code == 404
    assert (await _json(res))['error_code'] == 'NOT_FOUND'


async def test_process_check_is_public(client, db):
    res = await client.get('/api/process_check')
    assert res.status_code == 200
    assert 'processing' in await _json(res)


@pytest.mark.parametrize('kwargs', [
    {'json': {'login': 'admin', 'password': 'password123'}},                            # no X-Requested-With
    {'json': {'login': 'admin', 'password': 'password123'}, 'headers': {'X-Requested-With': 'XMLHttpRequest'}},
    {'form': {'login': 'admin', 'password': 'password123'}, 'headers': CSRF},          # form post
    {'data': '{"login": "admin", "password": "password123"}', 'headers': {**CSRF, 'Content-Type': 'text/plain'}},
])
async def test_csrf_guard_rejects(client, user, kwargs):
    res = await client.post('/api/login', **kwargs)
    assert res.status_code == 403
    assert (await _json(res))['error_code'] == 'CSRF_FAILED'
    assert (await _json(await client.get('/api/session')))['authenticated'] is False


async def test_csrf_guard_on_logout_and_users(authed):
    assert (await authed.post('/api/logout')).status_code == 403
    assert (await authed.delete('/api/users/admin')).status_code == 403
    assert (await authed.get('/api/logout')).status_code in (404, 405)   # logout is POST only
    assert (await _json(await authed.get('/api/session')))['authenticated'] is True


# --- login / logout --------------------------------------------------------------------------

async def test_login_logout(client, user):
    res = await login(client, 'admin', 'wrong-password')
    assert res.status_code == 401
    assert (await _json(res))['error_code'] == 'INVALID_CREDENTIALS'
    res = await login(client, 'nobody', 'password123')
    assert res.status_code == 401
    res = await login(client)
    assert res.status_code == 200 and (await _json(res)) == {'login': 'admin'}
    cookie = res.headers.get('Set-Cookie', '')
    assert 'mlp_session=' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert (await client.get('/api/emails')).status_code == 200
    res = await post(client, '/api/logout')
    assert res.status_code == 204
    assert (await client.get('/api/emails')).status_code == 401


@pytest.mark.parametrize('body', [{'login': 'admin'}, {'login': 'admin', 'password': ''}, {'login': 1, 'password': 2}, []])
async def test_login_rejects_missing_or_empty_fields(client, user, body):
    res = await post(client, '/api/login', body)
    assert res.status_code == 400


async def test_login_throttling(client, user):
    for _ in range(settings.login_max_failures):
        assert (await login(client, 'admin', 'bad-password')).status_code == 401
    res = await login(client)              # correct password, but throttled
    assert res.status_code == 429
    assert int(res.headers['Retry-After']) > 0
    # another login from the same IP is not blocked by the per-(IP, login) limit
    assert (await login(client, 'someone', 'bad-password')).status_code == 401


def test_throttle_window_expires():
    t = security.LoginThrottle(max_failures=2, max_failures_ip=100, window=1)
    t.failure('1.2.3.4', 'x')
    t.failure('1.2.3.4', 'X')            # login is case-insensitive for throttling
    assert t.retry_after('1.2.3.4', 'x') > 0
    assert t.retry_after('5.6.7.8', 'x') == 0
    time.sleep(1.05)
    assert t.retry_after('1.2.3.4', 'x') == 0
    t.failure('1.2.3.4', 'x')
    t.success('1.2.3.4', 'x')
    assert t.retry_after('1.2.3.4', 'x') == 0


async def test_session_expiry(authed):
    async with authed.session_transaction() as sess:
        sess['iat'] = int(time.time()) - settings.session_lifetime_hours * 3600 - 10
    assert (await authed.get('/api/emails')).status_code == 401


async def test_forged_session_without_iat_rejected(authed):
    async with authed.session_transaction() as sess:
        del sess['iat']
    assert (await authed.get('/api/emails')).status_code == 401


# --- legacy plaintext upgrade ------------------------------------------------------------------

async def test_legacy_plaintext_password_upgrade(client, db):
    d, conn = db
    await d.table('auth').insert({'id': 'oldadmin', 'password': 'legacy-pass'}).run(conn)
    assert (await login(client, 'oldadmin', 'wrong')).status_code == 401
    row = await auth.get_user('oldadmin')
    assert row == {'id': 'oldadmin', 'password': 'legacy-pass'}           # untouched on failure
    assert (await login(client, 'oldadmin', 'legacy-pass')).status_code == 200
    row = await auth.get_user('oldadmin')
    assert 'password' not in row and row['password_hash'].startswith(('scrypt:', 'pbkdf2:'))
    # the upgraded hash works and the session survives the upgrade
    assert (await client.get('/api/emails')).status_code == 200
    other = client.app.test_client()
    assert (await login(other, 'oldadmin', 'legacy-pass')).status_code == 200


# --- account management ----------------------------------------------------------------------

async def test_users_crud(authed):
    res = await authed.get('/api/users')
    assert res.status_code == 200 and (await _json(res)) == [{'login': 'admin'}]

    res = await post(authed, '/api/users', {'login': 'second.user', 'password': 'password456'})
    assert res.status_code == 201 and (await _json(res)) == {'login': 'second.user'}
    assert (await post(authed, '/api/users', {'login': 'second.user', 'password': 'password456'})).status_code == 409
    assert (await post(authed, '/api/users', {'login': 'x', 'password': 'password456'})).status_code == 400
    assert (await post(authed, '/api/users', {'login': 'valid.name', 'password': '1234567'})).status_code == 400

    body = await _json(await authed.get('/api/users'))
    assert body == [{'login': 'admin'}, {'login': 'second.user'}]
    assert 'password' not in str(body)

    res = await post(authed, '/api/users/second.user', {'password': 'changed-pass'}, method='PUT')
    assert res.status_code == 200
    other = authed.app.test_client()
    assert (await login(other, 'second.user', 'password456')).status_code == 401
    assert (await login(other, 'second.user', 'changed-pass')).status_code == 200
    assert (await post(authed, '/api/users/ghost', {'password': 'changed-pass'}, method='PUT')).status_code == 404
    assert (await post(authed, '/api/users/second.user', {'password': 'short'}, method='PUT')).status_code == 400

    res = await post(authed, '/api/users/second.user', method='DELETE')
    assert res.status_code == 204
    assert (await _json(await authed.get('/api/users'))) == [{'login': 'admin'}]
    assert (await post(authed, '/api/users/ghost', method='DELETE')).status_code == 404


async def test_cannot_delete_last_account(authed):
    res = await post(authed, '/api/users/admin', method='DELETE')
    assert res.status_code == 409
    assert (await _json(res))['error_code'] == 'LAST_ACCOUNT'
    assert await auth.get_user('admin') is not None


async def test_deleted_user_session_is_invalidated(authed):
    await auth.create_user('victim', 'password789')
    victim = authed.app.test_client()
    assert (await login(victim, 'victim', 'password789')).status_code == 200
    assert (await victim.get('/api/emails')).status_code == 200
    assert (await post(authed, '/api/users/victim', method='DELETE')).status_code == 204
    assert (await victim.get('/api/emails')).status_code == 401
    # re-creating the account does not revive the old session
    await auth.create_user('victim', 'password789')
    assert (await victim.get('/api/emails')).status_code == 401


async def test_password_change_invalidates_other_sessions(authed):
    other = authed.app.test_client()
    assert (await login(other)).status_code == 200
    res = await post(authed, '/api/users/admin', {'password': 'brand-new-pass'}, method='PUT')
    assert res.status_code == 200
    assert (await authed.get('/api/emails')).status_code == 200      # own session kept
    assert (await other.get('/api/emails')).status_code == 401


async def test_delete_self(authed):
    await auth.create_user('keeper', 'password789')
    assert (await post(authed, '/api/users/admin', method='DELETE')).status_code == 204
    assert (await authed.get('/api/emails')).status_code == 401


# --- secret key ------------------------------------------------------------------------------

def test_secret_key_generated_and_persisted(tmp_path, caplog):
    inst = str(tmp_path / 'instance')
    for default in ('', 'SetThis!InYourEnv', 'ChangeMe'):
        k1 = security.resolve_secret_key(default, inst)
        k2 = security.resolve_secret_key(default, inst)
        assert k1 == k2 and len(k1) >= 32 and k1 not in settings.insecure_secret_keys
    assert (tmp_path / 'instance' / 'secret_key').read_text().strip() == k1
    assert 'SECRET_KEY' in caplog.text
    strong = 'a-very-long-and-random-secret-key-value'
    assert security.resolve_secret_key(strong, inst) == strong


# --- LDAP (python-ldap faked) ----------------------------------------------------------------

class _FakeLdapModule(types.ModuleType):
    """Minimal stand-in for python-ldap recording binds and searches."""

    def __init__(self, users):
        super().__init__('ldap')
        self.users = users           # {login: password}
        self.calls = []
        self.SCOPE_SUBTREE = 2
        self.OPT_REFERRALS = 8
        self.OPT_NETWORK_TIMEOUT = 20485
        self.OPT_TIMEOUT = 20482

        class LDAPError(Exception):
            pass

        class INVALID_CREDENTIALS(LDAPError):
            pass

        self.LDAPError, self.INVALID_CREDENTIALS = LDAPError, INVALID_CREDENTIALS
        flt = types.ModuleType('ldap.filter')

        def escape_filter_chars(s):
            out = s.replace('\\', r'\5c').replace('*', r'\2a').replace('(', r'\28').replace(')', r'\29')
            return out.replace('\x00', r'\00')
        flt.escape_filter_chars = escape_filter_chars
        self.filter = flt
        mod = self

        class Conn:
            protocol_version = 3

            def set_option(self, *a):
                mod.calls.append(('set_option',) + a)

            def simple_bind_s(self, who, cred):
                mod.calls.append(('bind', who, cred))
                if who == settings.ldap_bind_dn:
                    return
                login = who.split('@')[0]
                if not cred or mod.users.get(login) != cred:
                    raise INVALID_CREDENTIALS()

            def search_s(self, base, scope, criteria, attrs):
                mod.calls.append(('search', criteria))
                name = criteria.split('=', 1)[1].rstrip(')')
                return [(f'CN={name},DC=example', {})] if name in mod.users else []

            def unbind_s(self):
                mod.calls.append(('unbind',))

        self.initialize = lambda uri: Conn()


@pytest.fixture
def fake_ldap(monkeypatch):
    mod = _FakeLdapModule({'jdoe': 'ldap-secret'})
    monkeypatch.setitem(sys.modules, 'ldap', mod)
    monkeypatch.setitem(sys.modules, 'ldap.filter', mod.filter)
    monkeypatch.setattr(settings, 'ldap_connect', 'ldap://ldap.invalid')
    monkeypatch.setattr(settings, 'ldap_bind_dn', 'CN=svc,DC=example')
    monkeypatch.setattr(settings, 'ldap_bind_dn_pwd', 'svc-pass')
    monkeypatch.setattr(settings, 'ldap_username_attr', 'sAMAccountName')
    monkeypatch.setattr(settings, 'ldap_username_domain_part', 'example.com')
    return mod


async def test_ldap_login(client, db, fake_ldap):
    data = await _json(await client.get('/api/session'))
    assert data['auth_mode'] == 'ldap' and data['needs_setup'] is False
    assert (await login(client, 'jdoe', 'wrong')).status_code == 401
    assert (await login(client, 'jdoe', 'ldap-secret')).status_code == 200
    assert (await client.get('/api/emails')).status_code == 200
    binds = [c for c in fake_ldap.calls if c[0] == 'bind']
    assert ('bind', 'jdoe@example.com', 'ldap-secret') in binds
    res = await client.get('/api/users')
    assert res.status_code == 400 and (await _json(res))['error_code'] == 'LOCAL_AUTH_ONLY'
    assert (await post(client, '/api/setup', {'login': 'x.y.z', 'password': 'password123'})).status_code == 400


async def test_ldap_empty_password_never_binds(client, db, fake_ldap):
    assert await auth.authenticate_ldap('jdoe', '') is False
    assert fake_ldap.calls == []
    assert (await post(client, '/api/login', {'login': 'jdoe', 'password': ''})).status_code == 400


async def test_ldap_filter_is_escaped(db, fake_ldap):
    assert auth._ldap_authenticate_sync('*', 'x') is False
    searches = [c[1] for c in fake_ldap.calls if c[0] == 'search']
    assert searches == [r'(sAMAccountName=\2a)']
    # logins outside the allowed character set never reach LDAP
    fake_ldap.calls.clear()
    assert await auth.authenticate_ldap('j*)(uid=*', 'x') is False
    assert fake_ldap.calls == []


# --- error handling --------------------------------------------------------------------------

async def test_unhandled_error_has_no_traceback(make_app, db, monkeypatch):
    monkeypatch.setattr(settings, 'DEBUG', True)
    app = make_app('')

    @app.route('/boom')
    async def boom():
        raise RuntimeError('secret internals')

    res = await app.test_client().get('/boom')
    assert res.status_code == 500
    body = await res.get_data(as_text=True)
    assert 'secret internals' not in body and 'Traceback' not in body
    assert (await res.get_json())['error_code'] == 'UNKNOWN_ERROR'
