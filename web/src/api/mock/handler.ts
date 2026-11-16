/**
 * In-browser fake backend for `VITE_MOCK=1`. Implements the DESIGN-v2.md contract closely enough to
 * develop and screenshot the UI without Quart/RethinkDB.
 *
 * Toggles (localStorage, then reload): `mlp.mock.setup=1` (no accounts yet), `mlp.mock.ldap=1`,
 * `mlp.mock.processing=1` (parser running banner), `mlp.mock.slow=1` (2 s latency).
 */
import type { Query } from '../client';
import type { Email } from '../types';
import { mockEmails } from './data';

const ls = {
  get: (k: string) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k: string, v: string | null) => {
    try {
      if (v === null) localStorage.removeItem(k);
      else localStorage.setItem(k, v);
    } catch {
      /* ignore */
    }
  },
};

/**
 * Screenshot helper: `#mock=login,dark,processing,colored,filters` in the URL presets the fake
 * session and preferences (handy for headless browsers with a fresh profile).
 */
function applyMockHash() {
  const m = /mock=([^&]+)/.exec(window.location.hash);
  if (!m) return;
  const tokens = decodeURIComponent(m[1]).split(',');
  const prefs = JSON.parse(ls.get('mlp.prefs') ?? '{}') as Record<string, unknown>;
  for (const tok of tokens) {
    const [k, v] = tok.split(':');
    if (k === 'login') ls.set('mlp.mock.auth', v || 'admin');
    if (k === 'setup') ls.set('mlp.mock.setup', '1');
    if (k === 'ldap') ls.set('mlp.mock.ldap', '1');
    if (k === 'processing') ls.set('mlp.mock.processing', '1');
    if (k === 'lang') ls.set('mlp.lang', v);
    if (k === 'dark' || k === 'light') prefs.theme = k;
    if (k === 'colored') prefs.coloredRows = true;
    if (k === 'comfortable') prefs.density = 'comfortable';
    if (k === 'filters') prefs.showFilterRow = true;
    if (k === 'cols') prefs.columns = v.split('+');
  }
  ls.set('mlp.prefs', JSON.stringify(prefs));
  if (prefs.theme) ls.set('mlp.theme', String(prefs.theme));
  // reload without the hash so prefs, theme and language are picked up from the start
  window.location.replace(window.location.pathname + window.location.search);
}
applyMockHash();

let users: string[] = ls.get('mlp.mock.setup') === '1' ? [] : ['admin', 'postmaster'];

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
const err = (status: number, code: string, message: string) => json(status, { error: true, error_code: code, message });

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function relayStr(e: { host?: string | null; ip?: string | null; port?: number | string | null } | null | undefined) {
  if (!e) return '';
  return e.ip ? `${e.host ?? ''}[${e.ip}]${e.port ? `:${e.port}` : ''}` : (e.host ?? '');
}

function fieldValues(e: Email, field: string): string[] {
  switch (field) {
    case 'mail_to':
      return [e.mail_to ?? '', ...Object.keys(e.mail_to_alias ?? {}), ...Object.values(e.mail_to_alias ?? {}), ...(e.recipients ?? []).map((r) => r.to)];
    case 'status.code':
      return [e.status?.code ?? ''];
    case 'status.message':
      return [e.status?.message ?? ''];
    case 'relay':
      return [relayStr(e.relay), ...(e.recipients ?? []).map((r) => relayStr(r.relay))];
    case 'relay.host':
      return [e.relay?.host ?? ''];
    case 'relay.ip':
      return [e.relay?.ip ?? ''];
    case 'client':
      return [e.client ? (e.client.ip ? `${e.client.host}[${e.client.ip}]` : (e.client.host ?? '')) : ''];
    case 'client.host':
      return [e.client?.host ?? ''];
    case 'client.ip':
      return [e.client?.ip ?? ''];
    case 'dkim.domain':
      return [e.dkim?.domain ?? ''];
    case 'multiple':
      return [String(e.multiple === true || (e.recipients?.length ?? 0) > 1 || e.status?.code === 'multiple')];
    case 'log_lines':
      return (e.lines ?? []).map((l) => l.message);
    default: {
      const v = (e as unknown as Record<string, unknown>)[field];
      return [v === null || v === undefined ? '' : String(v)];
    }
  }
}

const ALLOWED = new Set([
  'id', 'queue_id', 'host', 'mail_from', 'mail_to', 'subject', 'message_id', 'status.code', 'status.message',
  'relay', 'relay.host', 'relay.ip', 'client', 'client.host', 'client.ip', 'sasl_username', 'sasl_method',
  'service', 'dsn', 'dkim.domain', 'size', 'log_lines', 'multiple',
]);
const CONTROL = new Set(['page', 'limit', 'order', 'order_dir', 'statuses', 'top_senders', 'top_recipients', 'top_relays', 'by_host', 'timeline', 'bucket', 'tz']);

function applyFilters(list: Email[], q: Query): Email[] | Response {
  let out = list;
  for (const [key, raw] of Object.entries(q)) {
    if (raw === undefined || raw === null || raw === '' || CONTROL.has(key)) continue;
    const value = String(raw);
    if (key === 'timestamp__gt' || key === 'timestamp__lt') {
      const t = new Date(value).getTime();
      out = out.filter((e) => {
        const et = new Date(e.timestamp ?? 0).getTime();
        return key.endsWith('gt') ? et > t : et < t;
      });
      continue;
    }
    const m = /^(.+?)(?:__(not|eq))?$/.exec(key === 'multiple' ? 'multiple__eq' : key)!;
    const field = m[1];
    const op = m[2] ?? 'contains';
    if (!ALLOWED.has(field)) return err(400, 'INVALID_FILTER', `Unknown filter '${field}'.`);
    if (op === 'eq' && (field === 'status.code' || field === 'host')) {
      const set = new Set(value.split(',').map((s) => s.trim().toLowerCase()));
      out = out.filter((e) => fieldValues(e, field).some((v) => set.has(v.toLowerCase())));
      continue;
    }
    const needle = value.toLowerCase();
    out = out.filter((e) => {
      const vals = fieldValues(e, field).map((v) => v.toLowerCase());
      if (op === 'eq') return vals.some((v) => v === needle);
      const hit = vals.some((v) => v.includes(needle));
      return op === 'not' ? !hit : hit;
    });
  }
  return out;
}

function stripLines(e: Email): Email {
  const { lines: _lines, ...rest } = e;
  void _lines;
  return rest;
}

function topBy(list: Email[], key: (e: Email) => string[], exclude: string[] = []): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const e of list) for (const k of key(e)) if (k && !exclude.includes(k)) counts.set(k, (counts.get(k) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
}

const MAIN = ['sent', 'deferred', 'bounced', 'reject'] as const;
const SORT_FIELDS = ['id', 'queue_id', 'host', 'timestamp', 'first_attempt', 'last_attempt', 'mail_from', 'mail_to', 'subject', 'size', 'service'];

export async function handle(method: string, path: string, query: Query | undefined, body: unknown): Promise<Response> {
  await sleep(ls.get('mlp.mock.slow') === '1' ? 2000 : 120 + Math.random() * 180);
  const q = query ?? {};
  const b = (body ?? {}) as Record<string, string>;
  const authed = ls.get('mlp.mock.auth');
  const ldap = ls.get('mlp.mock.ldap') === '1';

  if (path === '/session' && method === 'GET') {
    const base = { authenticated: !!authed, login: authed, auth_mode: ldap ? 'ldap' : 'local', needs_setup: users.length === 0 && !ldap, version: '2.0.0-dev' };
    if (!authed) return json(200, { ...base, config: { mail_domain: 'example.com' } });
    return json(200, {
      ...base,
      config: {
        mta: 'postfix',
        mail_domain: 'example.com',
        default_limit: 50,
        max_limit: 1000,
        housekeeping_days: 30,
        datetime_format: 'YYYY-MM-DD HH:mm:ss',
        gui_max_log_period: 0,
        exclude_from_top_senders: ['noreply@example.com'],
        exclude_from_top_recipients: [],
      },
    });
  }
  if (path === '/login' && method === 'POST') {
    if (!b.login || !b.password || b.password === 'wrong') return err(401, 'INVALID_CREDENTIALS', 'Wrong login or password');
    ls.set('mlp.mock.auth', b.login);
    return json(200, { login: b.login });
  }
  if (path === '/setup' && method === 'POST') {
    if (users.length) return err(409, 'ALREADY_SET_UP', 'An account already exists.');
    users = [b.login];
    ls.set('mlp.mock.setup', null);
    ls.set('mlp.mock.auth', b.login);
    return json(201, { login: b.login });
  }
  if (path === '/logout') {
    ls.set('mlp.mock.auth', null);
    return json(204, null);
  }
  if (!authed) return err(401, 'UNAUTHORIZED', 'Log in first');

  if (path === '/process_check') return json(200, { processing: ls.get('mlp.mock.processing') === '1' });

  if (path === '/users') {
    if (ldap) return err(400, 'LOCAL_AUTH_ONLY', 'Accounts are managed by LDAP.');
    if (method === 'GET') return json(200, users.map((login) => ({ login })));
    if (users.includes(b.login)) return err(409, 'USER_EXISTS', 'An account with this login already exists.');
    users = [...users, b.login];
    return json(201, { login: b.login });
  }
  const um = /^\/users\/(.+)$/.exec(path);
  if (um) {
    const login = decodeURIComponent(um[1]);
    if (!users.includes(login)) return err(404, 'NOT_FOUND', 'No such account');
    if (method === 'PUT') return json(200, { login });
    if (method === 'DELETE') {
      if (users.length === 1) return err(409, 'LAST_ACCOUNT', 'The last account cannot be deleted');
      users = users.filter((u) => u !== login);
      return json(204, null);
    }
  }

  const all = mockEmails();
  if (path === '/facets') {
    return json(200, {
      hosts: [...new Set(all.map((e) => e.host ?? ''))].filter(Boolean).sort(),
      statuses: [...new Set(all.map((e) => e.status?.code ?? ''))].sort(),
      services: [...new Set(all.map((e) => e.service ?? ''))].filter(Boolean).sort(),
    });
  }
  const em = /^\/emails\/(.+)$/.exec(path);
  if (em) {
    const id = decodeURIComponent(em[1]);
    const e = all.find((x) => x.id === id);
    return e ? json(200, e) : err(404, 'NOT_FOUND', `Message ${id} not found`);
  }
  if (path === '/emails') {
    if (q.log_lines && !q.timestamp__gt && !q.timestamp__lt) return err(400, 'TIME_WINDOW_REQUIRED', 'The log_lines search needs a time window.');
    if (q.order && !SORT_FIELDS.includes(String(q.order))) return err(400, 'INVALID_ORDER', `Cannot order by '${q.order}'.`);
    const filtered = applyFilters(all, q);
    if (filtered instanceof Response) return filtered;
    const order = String(q.order ?? 'last_attempt');
    const dir = q.order_dir === 'asc' ? 1 : -1;
    const sorted = [...filtered].sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[order];
      const bv = (b as unknown as Record<string, unknown>)[order];
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
      return String(av ?? '').localeCompare(String(bv ?? '')) * dir;
    });
    const limit = Math.min(Number(q.limit ?? 50) || 50, 1000);
    const page = Math.max(1, Number(q.page ?? 1) || 1);
    const total_pages = Math.max(1, Math.ceil(sorted.length / limit));
    const result = sorted.slice((page - 1) * limit, page * limit).map(stripLines);
    return json(200, { error: false, result, count: sorted.length, remaining: Math.max(0, sorted.length - page * limit), page, total_pages });
  }
  if (path === '/stats') {
    if (q.statuses) {
      const code = String(q.statuses);
      return json(200, { [code]: all.filter((e) => e.status?.code === code).length });
    }
    const filtered = applyFilters(all, q);
    if (filtered instanceof Response) return filtered;
    if (q.top_senders) return json(200, topBy(filtered, (e) => [e.mail_from ?? ''], ['noreply@example.com']).map(([mail_from, count]) => ({ mail_from, count })));
    if (q.top_recipients)
      return json(200, topBy(filtered, (e) => (e.recipients?.length ? e.recipients.map((r) => r.to) : [e.mail_to ?? ''])).map(([mail_to, count]) => ({ mail_to, count })));
    if (q.top_relays) return json(200, topBy(filtered, (e) => [relayStr(e.relay)]).map(([relay, count]) => ({ relay, count })));
    if (q.by_host) {
      const hosts = new Map<string, { count: number; sent: number; deferred: number; bounced: number; reject: number } & Record<string, number>>();
      for (const e of filtered) {
        const h = hosts.get(e.host ?? '') ?? { count: 0, sent: 0, deferred: 0, bounced: 0, reject: 0 };
        h.count += 1;
        const c = e.status?.code ?? '';
        if ((MAIN as readonly string[]).includes(c)) h[c] += 1;
        hosts.set(e.host ?? '', h);
      }
      return json(200, [...hosts.entries()].map(([host, v]) => ({ host, ...v })).sort((a, b) => b.count - a.count));
    }
    if (q.timeline) {
      const bucketMs = q.bucket === 'day' ? 24 * 3600e3 : 3600e3;
      const buckets = new Map<number, Record<string, number>>();
      for (const e of filtered) {
        const t = new Date(e.timestamp ?? 0).getTime();
        const k = Math.floor(t / bucketMs) * bucketMs;
        const v = buckets.get(k) ?? { sent: 0, deferred: 0, bounced: 0, reject: 0, other: 0 };
        const c = e.status?.code ?? '';
        if ((MAIN as readonly string[]).includes(c)) v[c] += 1;
        else v.other += 1;
        buckets.set(k, v);
      }
      return json(
        200,
        [...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([k, v]) => ({ t: new Date(k).toISOString().replace('Z', '+00:00'), ...v })),
      );
    }
    return err(400, 'BAD_REQUEST', 'Unknown stats query');
  }
  return err(404, 'NOT_FOUND', `No mock for ${method} ${path}`);
}
