# MTA Log Parser 2.0 — design and contract

Working document for the 2.0 rework (fork of drlight17/mta-log-parser, driven by
[issue #30](https://github.com/drlight17/mta-log-parser/issues/30)). Backend and frontend are
built in parallel against this contract; change it here first if something has to move.

## Goals

1. Show **mail server (host)**, **relay** and **client** as first-class columns: visible in the
   main table, filterable, included in the Excel export.
2. Extract more data from postfix logs (SASL login, DSN, delays, orig_to, per-recipient delivery
   results, DKIM, submission service, nrcpt).
3. One GUI for **several mail servers** (one central syslog file with many hosts, or several files).
4. New web UI: cleaner look, column chooser (show/hide/reorder), per-column filters, saved per user
   in the browser.
5. Fix bugs and security problems found in review (see "Security baseline").

Non-goals: changing the storage engine (RethinkDB stays), changing exim/sendmail/exchange
parsing beyond what the shared code needs (they must keep working, new fields may stay empty).

## Data model — table `sent_mail`

Existing fields stay (old UI-independent consumers and stats code rely on them). New fields marked **new**.

| field | type | notes |
|---|---|---|
| `id` | str | **changed**: `"<host>:<queue_id>"` when the host is known, else `queue_id` (old behaviour). Prevents collisions of queue IDs from different servers. |
| `queue_id` | str | MTA queue id |
| `host` | str | **new**. Mail server that wrote the line: the syslog hostname field (`filterek08`). Fallback: env `MAIL_HOST_NAME`, else `""`. Indexed. |
| `timestamp`, `first_attempt`, `last_attempt` | time | RethinkDB time, UTC. The offset in the log line (e.g. `+02:00`) must be honoured; `LOG_TIMEZONE` applies only when the line has no offset. |
| `mail_from` | str | |
| `mail_to` | str | legacy: single address, or JSON-encoded list (strings or `{mail_to, mail_to_alias}`) when status is `multiple`. Keep as is. |
| `mail_to_alias` | dict | legacy |
| `recipients` | list | **new**. One entry per recipient, latest delivery attempt wins: `{to, orig_to, status: {code, message}, relay: {host, ip, port}, dsn, delay, delays, timestamp}` |
| `subject`, `size` (KiB), `message_id` | | |
| `status` | `{code, message}` | code ∈ `sent, reject, deferred, bounced, multiple, unknown`. **Changed**: when `recipients` exist the code is the *worst* recipient delivery (bounced > reject > deferred > sent) and the message starts with `N recipients: …`; `multiple` only appears on legacy documents or with `LEGACY_MULTIPLE_STATUS=true`. |
| `multiple` | bool | **new**. More than one distinct recipient. |
| `relay` | `{host, ip, port}` | relay of the representative delivery: the worst one if a delivery failed, else the last *network* delivery (LMTP/local hand-offs such as an archive copy are skipped when a network relay exists). For postfix also `relay=none` → `{host: "none"}`. |
| `client` | `{host, ip}` | connecting client (`client=unknown[192.168.140.50]`) |
| `sasl_method`, `sasl_username` | str | **new**. From `client=…, sasl_method=login, sasl_username=dms@tt-cs.com.pl` |
| `service` | str | **new**. Postfix service that received the message: `smtpd`, `submission`, `smtps`, `pickup`, … (from `postfix/submission/smtpd[…]`). |
| `dsn`, `delay` | str / float | **new**. From the last delivery line (`dsn=2.6.0`, `delay=1.9`). |
| `nrcpt` | int | **new**. From qmgr `nrcpt=2`. |
| `dkim` | `{domain, selector}` | **new**. From `opendkim[…]: <qid>: DKIM-Signature field added (s=default, d=tt.com.pl)`. |
| `tls` | bool | **new** (best effort). True when a `TLS connection established` line of the same smtpd/smtp process precedes the message lines. May be left `null` if not cheap to compute. |
| `lines` | list of `{timestamp, queue_id, message}` | raw log lines; **not** returned by the list API any more (see below). |

Indexes: existing ones + `host`.

## Parser / importer

- `MAIL_LOG_FILENAME` accepts a comma-separated list and glob patterns (relative to `MAIL_LOG_PATH`).
  Each matching file is parsed; host comes from each line, so a central syslog with many servers works.
- Lines of other programs that carry a postfix queue id and are useful (`opendkim`) are accepted for
  postfix; everything else keeps being skipped.
- Fast timestamp path: RFC 3339 (`2026-10-26T06:28:47.155158+00:00`) and BSD syslog
  (`Oct 26 06:28:47`) are parsed with a regex/`fromisoformat`; `datefinder` is only the fallback.
- Saving: batched `insert(..., conflict="update")` in chunks instead of get + update per message.
- Errors: no unbounded recursive retry; the lock file is always removed (`try/finally`).

## HTTP API (JSON)

All paths are under `PATH_PREFIX`. Every `/api/*` endpoint answers JSON; unauthenticated calls get
`401 {"error": true, "error_code": "UNAUTHORIZED", "message": …}` (never an HTML redirect).
Errors use `{"error": true, "error_code", "message"}` with a proper HTTP status.
State-changing requests (`POST/PUT/DELETE`) must send `Content-Type: application/json` and the header
`X-Requested-With: mlp` (CSRF guard; the session cookie is `HttpOnly`, `SameSite=Lax`).
All timestamps in responses are ISO 8601 strings with offset (`2026-10-26T06:28:47.155158+00:00`).

### Session and accounts

| method & path | body / query | answer |
|---|---|---|
| GET `/api/session` | — | `{authenticated, login, auth_mode: "local"\|"ldap", needs_setup, version, config: {mta, mail_domain, default_limit, max_limit, housekeeping_days, datetime_format, gui_max_log_period, exclude_from_top_senders: [], exclude_from_top_recipients: []}}`. Works without login (then `login: null`, `config` limited to `version`, `auth_mode`, `needs_setup`, `mail_domain`). |
| POST `/api/login` | `{login, password}` | `200 {login}` / `401` |
| POST `/api/logout` | — | `204` |
| POST `/api/setup` | `{login, password}` | creates the first account; `409` if any account exists. Logs the new user in. |
| GET `/api/users` | — | `[{login}]` (local auth only; never passwords) |
| POST `/api/users` | `{login, password}` | `201`; `409` if exists |
| PUT `/api/users/<login>` | `{password}` | `200` |
| DELETE `/api/users/<login>` | — | `204`; deleting the last account is refused (`409`) |

Passwords are stored hashed (`werkzeug.security`); legacy plaintext rows are upgraded on successful login.
Login: min 3 chars, `[A-Za-z0-9._@-]`; password min 8 chars.

### Emails

GET `/api/emails` — list, paginated. Query parameters:

- `page` (1-based), `limit` (≤ `MAX_LIMIT`), `order` (field, default `last_attempt`), `order_dir` (`asc|desc`).
- `timestamp__gt`, `timestamp__lt` (also `first_attempt__…`, `last_attempt__…`): ISO 8601 preferred;
  values in `DATETIME_FORMAT` are still accepted (legacy).
- Text filters, any number at once, AND-ed: `<field>=<text>` → case-insensitive *contains*;
  `<field>__not=<text>` → does not contain; `<field>__eq=<text>` → exact match.
  The text is literal (escaped before it reaches RethinkDB regex). Allowed fields:
  `id, queue_id, host, mail_from, mail_to, subject, message_id, status.code, status.message,
  relay, relay.host, relay.ip, client, client.host, client.ip, sasl_username, sasl_method, service,
  dsn, dkim.domain, size, log_lines`. Unknown fields → `400`.
  `relay` / `client` match against `host[ip]:port` / `host[ip]`. `mail_to` also matches `mail_to_alias`
  and `recipients[].to`. `log_lines` searches raw lines (slow; same rules).
- `status.code` additionally accepts a comma-separated list (`status.code__eq=sent,deferred`) = OR.
- `host__eq` accepts a comma-separated list = OR.
- Legacy: `equal=false` negates the old-style single filter; keep working.

Answer: `{error: false, result: [...], count, remaining, page, total_pages}`; documents **without
`lines`**.

GET `/api/emails/<id>` — one document with `lines`. `404` if missing.

GET `/api/facets` — values for filter pickers: `{hosts: ["filterek08", …], statuses: [...], services: [...]}`
(distinct over the stored data; cheap enough via index on `host`).

### Stats (existing, keep query parameters; must also accept the new filters)

- GET `/api/stats?statuses=<code>` → `{<code>: count}`
- GET `/api/stats?top_senders=1&…filters` → `[{mail_from, count}]` (top 10)
- GET `/api/stats?top_recipients=1&…filters` → `[{mail_to, count}]`
- **new** GET `/api/stats?top_relays=1&…filters` → `[{relay, count}]`
- **new** GET `/api/stats?by_host=1&…filters` → `[{host, count, sent, deferred, bounced, reject}]`
- **new** GET `/api/stats?timeline=1&bucket=hour|day&…filters` → `[{t, sent, deferred, bounced, reject, other}]`

GET `/api/process_check` → `{processing: bool}` (unchanged).

## Web UI

Single-page app (React 19 + Vite + TypeScript) in `web/`, built into `mlp/static/app/` (the build
output is committed so a plain Python install works without Node). Quart serves `index.html` for
`PATH_PREFIX/` and the client routes; the app reads `PATH_PREFIX` from a `<meta>` tag injected by Quart.

Screens: login / first-account setup; emails table; message detail (drawer); stats; accounts (local
auth only); settings (language, page size, theme light/dark/auto, density, auto-refresh, timezone
display); help/tips.

Emails table requirements:
- Columns (all can be shown/hidden and reordered; choice persisted in `localStorage`):
  time, host, queue id, from, to, subject, status, relay, client, SASL user, size, DSN, delay,
  message-id, service, nrcpt, DKIM, TLS. Defaults: time, host, from, to, subject, status, relay, client.
- Per-column filter inputs (contains / not contains / exact), status chips, host multi-select,
  date range with quick presets (last 1h / 24h / 7d), global "log lines" search.
- Click a cell value → add it as a filter. Sort by clicking a sortable column header.
- Pagination, page size, auto-refresh, "processing" banner (from `/api/process_check`).
- Share link: the URL query string mirrors the filters.
- Export to Excel (`.xlsx`, SheetJS): current page or all matching rows (up to `MAX_LIMIT`), visible
  columns only, in visible order; multi-recipient rows list recipients and relays joined with `, `.
  Optional second sheet "Recipients" with one row per recipient delivery.
- Locales: English, Russian (upstream), Polish.

## Security baseline (must hold after 2.0)

- No account management without a session (except `/api/setup` when there are zero accounts).
- Hashed passwords; no passwords in logs or API answers.
- LDAP: escape the username in the search filter; reject empty passwords (anonymous bind bypass).
- Refuse to run with the default/empty `SECRET_KEY`: generate a random one and persist it
  (`instance/secret_key`, shared by all workers) with a loud warning.
- Session cookie `HttpOnly`, `SameSite=Lax`, `Secure` when `SESSION_COOKIE_SECURE=true`.
- CSRF guard on state-changing requests (header + JSON content type).
- No raw HTML rendering of log data, subjects or user names in the UI (no `dangerouslySetInnerHTML`).
- User-supplied filter text is escaped before RethinkDB `match()`.
- Basic login throttling (per IP + login, in-memory).
- Docker: RethinkDB admin port bound to `127.0.0.1` by default.
