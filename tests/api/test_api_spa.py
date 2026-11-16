"""Serving the single-page app shell and static assets, with and without PATH_PREFIX."""
import os
import uuid

import pytest

from mlp import views

pytestmark = pytest.mark.asyncio


@pytest.fixture
def asset_file():
    """A throw-away file in the SPA build's assets folder."""
    folder = os.path.join(views.STATIC_DIR, 'app', 'assets')
    created_folder = not os.path.isdir(folder)
    os.makedirs(folder, exist_ok=True)
    name = f'test-{uuid.uuid4().hex}.js'
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('console.log("x");\n')
    yield name
    os.remove(path)
    if created_folder:
        os.rmdir(folder)


async def _page(res):
    return await res.get_data(as_text=True)


@pytest.mark.parametrize('path', ['/', '/emails', '/stats/by-host', '/accounts?x=1'])
async def test_index_at_root(client, path):
    res = await client.get(path)
    assert res.status_code == 200
    assert res.mimetype == 'text/html'
    assert res.headers['Cache-Control'] == 'no-cache'
    page = await _page(res)
    assert '<meta name="mlp-prefix" content="">' in page
    assert '__MLP_PREFIX__' not in page
    assert 'href="/static/images/favicon.ico"' in page
    assert page.index('mlp-prefix') < page.index('</head>')


@pytest.mark.parametrize('path', ['/logs/', '/logs/emails', '/logs/a/b/c'])
async def test_index_with_prefix(make_app, path):
    client = make_app('/logs/').test_client()           # trailing slash is normalised
    res = await client.get(path)
    assert res.status_code == 200
    page = await _page(res)
    assert '<meta name="mlp-prefix" content="/logs">' in page
    assert 'href="/logs/static/images/favicon.ico"' in page
    assert '__MLP_PREFIX__' not in page


async def test_prefix_routes(make_app, db):
    client = make_app('/logs').test_client()
    assert (await client.get('/')).status_code == 404
    assert (await client.get('/api/session')).status_code == 404
    res = await client.get('/logs/api/session')
    assert res.status_code == 200 and (await res.get_json())['authenticated'] is False
    assert (await client.get('/logs/api/emails')).status_code == 401
    assert (await client.get('/logs/static/images/favicon.ico')).status_code == 200
    res = await client.get('/logs')
    assert res.status_code in (301, 308) and res.headers['Location'].endswith('/logs/')


async def test_prefix_cookie_path(make_app, db):
    from mlp import auth
    await auth.create_user('admin', 'password123')
    client = make_app('/logs').test_client()
    res = await client.post('/logs/api/login', json={'login': 'admin', 'password': 'password123'},
                            headers={'X-Requested-With': 'mlp'})
    assert res.status_code == 200
    assert 'Path=/logs/' in res.headers['Set-Cookie']


async def test_static_assets_cache_headers(client, asset_file):
    res = await client.get(f'/static/app/assets/{asset_file}')
    assert res.status_code == 200
    assert 'immutable' in res.headers['Cache-Control'] and 'max-age=31536000' in res.headers['Cache-Control']
    assert (await client.get('/static/app/assets/missing.js')).status_code == 404
    assert (await client.get('/static/nope.css')).status_code == 404


async def test_old_ui_assets_and_pages_are_gone(client, db):
    for path in ('/static/js/main_app.js', '/static/css/style.css', '/static/locales/en.json'):
        assert (await client.get(path)).status_code == 404
    for path in ('/register', '/login', '/api/auth'):
        res = await client.post(path, json={}, headers={'X-Requested-With': 'mlp'})
        assert res.status_code in (404, 405)


async def test_security_headers(client, db):
    for path in ('/', '/api/session'):
        res = await client.get(path)
        assert res.headers['X-Content-Type-Options'] == 'nosniff'
        assert res.headers['X-Frame-Options'] == 'DENY'
        assert res.headers['Referrer-Policy'] == 'same-origin'
        csp = res.headers['Content-Security-Policy']
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert (await client.get('/api/session')).headers['Cache-Control'] == 'no-store'
