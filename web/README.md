# MTA Log Parser — web UI (2.0)

Single-page app (React 19, Vite, TypeScript, TanStack Query, react-router, i18next, lucide-react,
SheetJS for the Excel export). The API contract it codes against is `docs/DESIGN-v2.md`.

## Commands

Run everything from `web/`. Do not use `npx` on Windows machines where `.js` files open in Windows
Script Host; the npm scripts below are enough.

| command | what it does |
|---|---|
| `npm install` | install dependencies |
| `npm run dev` | dev server on http://localhost:5180, `/api` proxied to `http://localhost:8487` (override with `MLP_BACKEND=http://host:port`) |
| `npm run dev:mock` | dev server with an in-browser fake backend (`.env.mock` sets `VITE_MOCK=1`), no Quart or RethinkDB needed |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run build` | typecheck + production build into `../mlp/static/app/` (the folder is emptied first) |

The production build is committed, so a plain Python install works without Node. Rebuild and commit
`mlp/static/app/` after every change in `web/`.

### Mock mode

`VITE_MOCK=1` replaces `fetch` with `src/api/mock/handler.ts` (about 1,400 generated messages on
hosts `mx01`/`mx02`, only `example.*` domains and documentation IP ranges). Any login/password works
except the password `wrong`. Toggles in `localStorage` (reload afterwards): `mlp.mock.setup=1` (no
accounts → setup screen), `mlp.mock.ldap=1`, `mlp.mock.processing=1` (parser banner),
`mlp.mock.slow=1` (2 s latency). For screenshots in a fresh browser profile append
`#mock=login,dark|light,lang:en|ru|pl,processing,ldap,setup,colored,filters,comfortable` to any URL.
The mock code is only imported when `VITE_MOCK=1`, so it is not part of the production bundle.

## Serving contract (for the Quart side)

- The app lives at `PATH_PREFIX/` (e.g. `/logs/`). Quart serves `mlp/static/app/index.html` for
  `PATH_PREFIX/` and for every client route: `/login`, `/setup`, `/stats`, `/accounts` (and, to be
  safe, any other non-`/api`, non-`/static` path → index.html). Deep links to a message are
  query strings on the root route (`PATH_PREFIX/?msg=<id>&…filters`).
- **Prefix placeholder.** The build uses Vite `base: '__MLP_PREFIX__/static/app/'`. When serving
  `index.html` the backend must replace every literal `__MLP_PREFIX__` with the real prefix
  (`''` when served at the root, `/logs` for `PATH_PREFIX=/logs`; no trailing slash). The same
  replacement fills `<meta name="mlp-prefix" content="__MLP_PREFIX__">`, from which the app reads
  the router basename and the API base (`<prefix>/api`). Only `index.html` contains the placeholder:
  JS and CSS reference their chunks, fonts and other assets with relative URLs.
- Static assets are requested under `PATH_PREFIX/static/app/` (`assets/*.js|css|woff2`,
  `favicon.svg`, `theme-init.js`). Hashed files under `assets/` can be cached for a long time;
  `index.html` must not be cached (it carries the prefix and the current asset hashes).
- CSP-compatible with `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';
  script-src 'self'; connect-src 'self'; frame-ancestors 'none'`: no inline scripts (the
  pre-paint theme script is the external `theme-init.js`), no `eval`, no external hosts at runtime
  (fonts are self-hosted via `@fontsource-variable/*`). `style-src 'unsafe-inline'` is needed for
  React `style` attributes (column widths, chart geometry).

## Requests the UI sends

All requests go to `<prefix>/api…` with `credentials: same-origin`. `POST/PUT/DELETE` send
`Content-Type: application/json` and `X-Requested-With: mlp`. Query strings are always built with
`URLSearchParams`. A 401 from any endpoint except `/session`, `/login`, `/logout`, `/setup` sends
the user to the login screen.

| call | when |
|---|---|
| `GET /session` | start, after login/setup/logout |
| `POST /login {login, password}` | login form |
| `POST /setup {login, password}` | first-account screen (`needs_setup`) |
| `POST /logout` | user menu |
| `GET /emails?page&limit&order&order_dir&<filters>` | messages table (`limit` = page size, ≤ `max_limit`) |
| `GET /emails/<encodeURIComponent(id)>` | detail drawer |
| `GET /facets` | server (host) picker |
| `GET /process_check` | every 15 s, every 3 s while `processing` is true |
| `GET /stats?statuses=<code>` | one call per status code (sent, deferred, bounced, reject, multiple, unknown) — overall tiles, not filtered |
| `GET /stats?by_host=1&<filters>` | per-server table; its sums also feed the status distribution |
| `GET /stats?timeline=1&bucket=hour\|day&<filters>` | timeline |
| `GET /stats?top_senders=1&<filters>` / `top_recipients=1` / `top_relays=1` | top lists (hiding entries is client-side) |
| `GET /users`, `POST /users`, `PUT /users/<login> {password}`, `DELETE /users/<login>` | accounts page (local auth only) |

`<filters>`:

- text filters: `<field>=…` (contains), `<field>__not=…`, `<field>__eq=…` for the fields of the
  contract (`mail_from`, `mail_to`, `subject`, `queue_id`, `message_id`, `status.message`, `relay`,
  `client`, `sasl_username`, `dsn`, `dkim.domain`, `size`, `service`, `host` …). Clicking a relay or
  client cell sends `relay__eq=host[ip]:port` / `client__eq=host[ip]`.
- `status.code__eq=sent,deferred` (status chips, OR), `host__eq=mx01,mx02` (server picker, OR)
- `multiple__eq=true|false` (recipients picker)
- `log_lines=…` (raw log search)
- `timestamp__gt=<ISO 8601 UTC>` and optionally `timestamp__lt=…` — presets 1h/24h/7d/30d are
  resolved to absolute timestamps at request time; "All" sends no time bound.

The page URL mirrors the same parameters (plus `range=1h|24h|7d|30d|all` for relative presets,
`page`, `order`, `order_dir`, `msg`), so the address bar is always a shareable link. "Share" copies
it with the relative range converted to absolute timestamps.

## Structure

```
src/
  api/         client (prefix, CSRF headers, errors), TanStack Query hooks, types, mock/
  lib/         filter model ↔ URL ↔ API, columns, formatting, prefs (localStorage), export
  shell/       app shell: top bar, footer, settings and help dialogs
  pages/       auth (login/setup), messages (table, filters, drawer, export), stats, accounts
  ui/          small UI kit: buttons, popover, dialog, drawer, toasts, status badge
  locales/     en, ru, pl
  styles/      tokens (colours, type), base, ui kit, app
```

Preferences (theme, density, page size, auto-refresh, colored rows, time zone, default range,
columns order/visibility/widths, hidden top-list entries) are stored per browser under
`localStorage['mlp.prefs']`; the language under `mlp.lang`, the theme also under `mlp.theme` for
the pre-paint script.
