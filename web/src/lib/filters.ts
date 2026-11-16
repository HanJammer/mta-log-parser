/**
 * Filter model of the messages list and its two serialisations:
 * - the page URL (shareable; mirrors the API parameters, plus `range`, `page`, `msg`)
 * - the API query of GET /api/emails and /api/stats
 */
import type { Query } from '../api/client';

export type Op = 'contains' | 'not' | 'eq';
export const OPS: readonly Op[] = ['contains', 'not', 'eq'];

/** Text-filterable fields accepted by the API (DESIGN-v2.md, "Emails"). `log_lines` is separate. */
export const TEXT_FIELDS = [
  'id',
  'queue_id',
  'host',
  'mail_from',
  'mail_to',
  'subject',
  'message_id',
  'status.code',
  'status.message',
  'relay',
  'relay.host',
  'relay.ip',
  'client',
  'client.host',
  'client.ip',
  'sasl_username',
  'sasl_method',
  'service',
  'dsn',
  'dkim.domain',
  'size',
] as const;
export type TextField = (typeof TEXT_FIELDS)[number];

export function isTextField(value: string): value is TextField {
  return (TEXT_FIELDS as readonly string[]).includes(value);
}

export interface TextFilter {
  field: TextField;
  op: Op;
  value: string;
}

export type RangePreset = '1h' | '24h' | '7d' | '30d' | 'all' | 'custom';
export const RANGE_PRESETS: readonly RangePreset[] = ['1h', '24h', '7d', '30d', 'all'];
const PRESET_MS: Record<string, number> = {
  '1h': 3600e3,
  '24h': 24 * 3600e3,
  '7d': 7 * 24 * 3600e3,
  '30d': 30 * 24 * 3600e3,
};

export interface Filters {
  text: TextFilter[];
  statuses: string[];
  hosts: string[];
  range: RangePreset;
  /** ISO strings, only for `range: 'custom'` */
  from?: string;
  to?: string;
  logSearch: string;
  /** `multiple__eq`: only multi-recipient (true) or single-recipient (false) messages */
  multiple?: 'true' | 'false';
}

export type SortDir = 'asc' | 'desc';

export interface ListState {
  filters: Filters;
  page: number;
  order: string;
  dir: SortDir;
  /** id of the message open in the detail drawer */
  msg?: string;
}

export const DEFAULT_ORDER = 'timestamp';

export function emptyFilters(range: RangePreset): Filters {
  return { text: [], statuses: [], hosts: [], range, logSearch: '' };
}

export function paramKey(field: string, op: Op): string {
  return op === 'contains' ? field : op === 'not' ? `${field}__not` : `${field}__eq`;
}

function splitList(value: string | null): string[] {
  return (value ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Reads the list state from the page URL. Unknown parameters are ignored. */
export function parseSearch(search: URLSearchParams, defaultRange: RangePreset): ListState {
  const filters = emptyFilters(defaultRange);
  for (const [key, raw] of search.entries()) {
    const value = raw.trim();
    if (!value) continue;
    if (key === 'status.code__eq') {
      filters.statuses = splitList(value);
      continue;
    }
    if (key === 'host__eq') {
      filters.hosts = splitList(value);
      continue;
    }
    if (key === 'multiple__eq') {
      if (value === 'true' || value === 'false') filters.multiple = value;
      continue;
    }
    if (key === 'log_lines') {
      filters.logSearch = value;
      continue;
    }
    const m = /^(.+?)(?:__(not|eq))?$/.exec(key);
    if (!m) continue;
    const field = m[1];
    if (!isTextField(field)) continue;
    const op: Op = m[2] === 'not' ? 'not' : m[2] === 'eq' ? 'eq' : 'contains';
    filters.text.push({ field, op, value });
  }

  const range = search.get('range');
  const gt = search.get('timestamp__gt');
  const lt = search.get('timestamp__lt');
  if (gt || lt) {
    filters.range = 'custom';
    filters.from = gt ?? undefined;
    filters.to = lt ?? undefined;
  } else if (range && (RANGE_PRESETS as readonly string[]).includes(range)) {
    filters.range = range as RangePreset;
  }

  const page = Number.parseInt(search.get('page') ?? '1', 10);
  const dir = search.get('order_dir') === 'asc' ? 'asc' : 'desc';
  return {
    filters,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    order: search.get('order') || DEFAULT_ORDER,
    dir,
    msg: search.get('msg') ?? undefined,
  };
}

/** Filter parameters shared by the URL and the API, without the time range. */
function filterParams(filters: Filters): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const f of filters.text) out.push([paramKey(f.field, f.op), f.value]);
  if (filters.statuses.length) out.push(['status.code__eq', filters.statuses.join(',')]);
  if (filters.hosts.length) out.push(['host__eq', filters.hosts.join(',')]);
  if (filters.multiple) out.push(['multiple__eq', filters.multiple]);
  if (filters.logSearch) out.push(['log_lines', filters.logSearch]);
  return out;
}

export interface ToSearchOptions {
  defaultRange: RangePreset;
  /** write relative ranges as absolute timestamps (for share links) */
  absolute?: boolean;
  now?: number;
}

/** Serialises the list state for the page URL. */
export function toSearchParams(state: ListState, opts: ToSearchOptions): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of filterParams(state.filters)) p.append(k, v);
  const { range } = state.filters;
  if (range === 'all') {
    if (opts.defaultRange !== 'all') p.set('range', 'all');
  } else if (range === 'custom' || opts.absolute) {
    const r = resolveRange(state.filters, opts.now);
    if (r.gt) p.set('timestamp__gt', r.gt);
    if (r.lt) p.set('timestamp__lt', r.lt);
  } else if (range !== opts.defaultRange) {
    p.set('range', range);
  }
  if (state.order !== DEFAULT_ORDER) p.set('order', state.order);
  if (state.dir !== 'desc') p.set('order_dir', state.dir);
  if (state.page > 1) p.set('page', String(state.page));
  if (state.msg) p.set('msg', state.msg);
  return p;
}

/** Absolute bounds of the time range (ISO 8601, UTC). */
export function resolveRange(filters: Filters, now = Date.now()): { gt?: string; lt?: string } {
  if (filters.range === 'custom') return { gt: filters.from || undefined, lt: filters.to || undefined };
  const ms = PRESET_MS[filters.range];
  if (!ms) return {};
  return { gt: new Date(now - ms).toISOString() };
}

/** API query for list and stats endpoints (no paging). Relative ranges are resolved now. */
export function toApiFilterQuery(filters: Filters, now = Date.now()): Query {
  const q: Query = {};
  for (const [k, v] of filterParams(filters)) q[k] = v;
  const r = resolveRange(filters, now);
  if (r.gt) q.timestamp__gt = r.gt;
  if (r.lt) q.timestamp__lt = r.lt;
  return q;
}

/** Adds (or replaces) a text filter; `host` exact matches go to the host picker. */
export function withTextFilter(filters: Filters, f: TextFilter): Filters {
  if (f.field === 'host' && f.op === 'eq') {
    return filters.hosts.includes(f.value) ? filters : { ...filters, hosts: [...filters.hosts, f.value] };
  }
  if (f.field === 'status.code' && f.op === 'eq') {
    return filters.statuses.includes(f.value) ? filters : { ...filters, statuses: [...filters.statuses, f.value] };
  }
  const key = paramKey(f.field, f.op);
  const text = filters.text.filter((t) => paramKey(t.field, t.op) !== key);
  return { ...filters, text: [...text, f] };
}

export function withoutTextFilter(filters: Filters, field: string, op: Op): Filters {
  const key = paramKey(field, op);
  return { ...filters, text: filters.text.filter((t) => paramKey(t.field, t.op) !== key) };
}

export function activeFilterCount(f: Filters, defaultRange: RangePreset): number {
  return (
    f.text.length +
    (f.statuses.length ? 1 : 0) +
    (f.hosts.length ? 1 : 0) +
    (f.logSearch ? 1 : 0) +
    (f.multiple ? 1 : 0) +
    (f.range !== defaultRange ? 1 : 0)
  );
}
