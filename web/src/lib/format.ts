import type { Client, Email, Recipient, Relay, Status } from '../api/types';
import type { TimeZonePref } from './prefs';

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

/** `2026-10-26 06:28:47` in local time or UTC. Empty string for missing/invalid input. */
export function formatTime(iso: string | null | undefined, tz: TimeZonePref, withSeconds = true): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const u = tz === 'utc';
  const date = `${u ? d.getUTCFullYear() : d.getFullYear()}-${pad((u ? d.getUTCMonth() : d.getMonth()) + 1)}-${pad(u ? d.getUTCDate() : d.getDate())}`;
  const time = `${pad(u ? d.getUTCHours() : d.getHours())}:${pad(u ? d.getUTCMinutes() : d.getMinutes())}`;
  return withSeconds ? `${date} ${time}:${pad(u ? d.getUTCSeconds() : d.getSeconds())}` : `${date} ${time}`;
}

/** A Date whose *local* fields show the wall-clock time of the chosen zone (for Excel cells). */
export function wallClockDate(iso: string | null | undefined, tz: TimeZonePref): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  if (tz === 'local') return d;
  return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds());
}

export function tzLabel(tz: TimeZonePref): string {
  if (tz === 'utc') return 'UTC';
  const off = -new Date().getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `UTC${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

/** `host [ip]:port` (relay=none → `none`). */
export function formatRelay(r: Relay | null | undefined): string {
  if (!r) return '';
  const host = r.host ?? '';
  const ip = r.ip ? ` [${r.ip}]` : '';
  const port = r.port !== undefined && r.port !== null && r.port !== '' ? `:${r.port}` : '';
  return `${host}${ip}${ip ? port : ''}`.trim();
}

/** API matching form of a relay: `host[ip]:port`. */
export function relayKey(r: Relay | null | undefined): string {
  if (!r) return '';
  const port = r.port !== undefined && r.port !== null && r.port !== '' ? `:${r.port}` : '';
  return r.ip ? `${r.host ?? ''}[${r.ip}]${port}` : (r.host ?? '');
}

export function formatClient(c: Client | null | undefined): string {
  if (!c) return '';
  return `${c.host ?? ''}${c.ip ? ` [${c.ip}]` : ''}`.trim();
}

export function clientKey(c: Client | null | undefined): string {
  if (!c) return '';
  return c.ip ? `${c.host ?? ''}[${c.ip}]` : (c.host ?? '');
}

interface LegacyTo {
  mail_to?: string;
  mail_to_alias?: string;
}

/**
 * Recipients of a message: the new `recipients` list, else the legacy JSON list in `mail_to`
 * (status `multiple`), else the single `mail_to`. Deliveries flagged `hidden` (HIDDEN_RECIPIENTS)
 * are left out unless `includeHidden` is set or no other recipient is left.
 */
export function recipientsOf(e: Email, includeHidden = false): Recipient[] {
  if (e.recipients && e.recipients.length) {
    if (includeHidden) return e.recipients;
    const visible = e.recipients.filter((r) => !r.hidden);
    return visible.length ? visible : e.recipients;
  }
  const raw = (e.mail_to ?? '').trim();
  if (raw.startsWith('[')) {
    try {
      const list = JSON.parse(raw) as Array<string | LegacyTo>;
      if (Array.isArray(list)) {
        return list
          .map((x) =>
            typeof x === 'string' ? { to: x } : { to: x.mail_to ?? '', orig_to: x.mail_to_alias ?? null },
          )
          .filter((r) => r.to);
      }
    } catch {
      /* not JSON after all */
    }
  }
  if (!raw) return [];
  const alias = e.mail_to_alias ? Object.values(e.mail_to_alias)[0] : undefined;
  return [{ to: raw, orig_to: alias ?? null }];
}

/**
 * Distinct relays of a message: the message-level relay first (the backend picks the
 * representative delivery, preferring network relays over LMTP archive copies), then any other
 * relay used by individual recipients. With `recipientOrder` the relays follow the order of the
 * recipients instead (the message-level relay only comes first if no recipient has a relay).
 */
export function relaysOf(e: Email, recipientOrder = false): Relay[] {
  const out: Relay[] = [];
  const seen = new Set<string>();
  const add = (r: Relay | null | undefined) => {
    const k = relayKey(r);
    if (r && k && !seen.has(k)) {
      seen.add(k);
      out.push(r);
    }
  };
  const recips = recipientsOf(e);
  if (!recipientOrder || !recips.some((r) => relayKey(r.relay))) add(e.relay);
  for (const r of recips) add(r.relay);
  add(e.relay);
  return out;
}

/** Multi-recipient message: the `multiple` flag, several recipients, or legacy status `multiple`. */
export function isMultiple(e: Email): boolean {
  return e.multiple === true || (e.status?.code ?? '') === 'multiple' || recipientsOf(e).length > 1;
}

export function statusCode(s: Status | null | undefined): string {
  return (s?.code || 'unknown').toLowerCase();
}

export function formatSize(size: number | string | null | undefined): string {
  if (size === null || size === undefined || size === '') return '';
  const n = typeof size === 'number' ? size : Number.parseFloat(size);
  if (!Number.isFinite(n)) return String(size);
  return n >= 100 ? n.toFixed(0) : n.toFixed(2);
}

export function formatDelay(delay: number | null | undefined): string {
  if (delay === null || delay === undefined) return '';
  if (delay < 60) return `${delay}s`;
  const m = Math.floor(delay / 60);
  if (m < 60) return `${m}m ${Math.round(delay % 60)}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export const numberFmt = (lng: string) => new Intl.NumberFormat(lng);

/** Offset of the chosen display zone as `+HH:MM` (for `/api/stats?timeline&tz=`). */
export function tzOffset(tz: TimeZonePref): string {
  if (tz === 'utc') return '+00:00';
  const off = -new Date().getTimezoneOffset();
  const a = Math.abs(off);
  return `${off >= 0 ? '+' : '-'}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}
