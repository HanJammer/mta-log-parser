import type { ReactNode } from 'react';
import type { TFunction } from 'i18next';
import { Lock, LockOpen } from 'lucide-react';
import type { Email, Relay } from '../api/types';
import { StatusBadge, statusKey } from '../ui/StatusBadge';
import type { Op, TextField } from './filters';
import {
  clientKey,
  formatDelay,
  formatRelay,
  formatSize,
  formatTime,
  isMultiple,
  recipientsOf,
  relayKey,
  relaysOf,
  wallClockDate,
} from './format';
import type { TimeZonePref } from './prefs';

export interface CellCtx {
  tz: TimeZonePref;
  t: TFunction;
  addFilter: (field: TextField, value: string, op: Op) => void;
}

export interface ColumnDef {
  id: string;
  width: number;
  /** API `order` field; absent = not sortable */
  sort?: string;
  /** API field used by the column filter input */
  filter?: TextField;
  align?: 'right';
  mono?: boolean;
  render: (e: Email, ctx: CellCtx) => ReactNode;
  exportValue: (e: Email, tz: TimeZonePref) => string | number | Date | null;
}

/** A cell value that adds itself as a filter on click (Alt+click: exclude). */
function V({
  ctx,
  field,
  value,
  children,
  className,
  op = 'eq',
}: {
  ctx: CellCtx;
  field: TextField;
  value: string | null | undefined;
  children?: ReactNode;
  className?: string;
  op?: Op;
}) {
  if (!value) return null;
  return (
    <span
      className={className ? `cv ${className}` : 'cv'}
      title={ctx.t('table.clickToFilter', { value })}
      onClick={(ev) => {
        ev.stopPropagation();
        ctx.addFilter(field, value, ev.altKey ? 'not' : op);
      }}
    >
      {children ?? value}
    </span>
  );
}

function More({ n, title }: { n: number; title: string }) {
  if (n <= 0) return null;
  return (
    <span className="more" title={title}>
      +{n}
    </span>
  );
}

function RelayText({ r }: { r: Relay }) {
  const port = r.port !== undefined && r.port !== null && r.port !== '' ? `:${r.port}` : '';
  return (
    <>
      <span className="rl-host">{r.host || (r.ip ? '' : '—')}</span>
      {r.ip && <span className="rl-addr mono"> [{r.ip}]{port}</span>}
    </>
  );
}

const time = (field: 'timestamp' | 'first_attempt' | 'last_attempt', id: string): ColumnDef => ({
  id,
  width: 168,
  sort: field,
  mono: true,
  render: (e, c) => <span className="nowrap">{formatTime(e[field], c.tz)}</span>,
  exportValue: (e, tz) => wallClockDate(e[field], tz),
});

const text = (id: string, field: TextField, get: (e: Email) => string | null | undefined, width: number, opts: Partial<ColumnDef> = {}): ColumnDef => ({
  id,
  width,
  filter: field,
  render: (e, c) => <V ctx={c} field={field} value={get(e)} />,
  exportValue: (e) => get(e) ?? '',
  ...opts,
});

export const COLUMNS: ColumnDef[] = [
  time('timestamp', 'time'),
  text('host', 'host', (e) => e.host, 84, { sort: 'host', mono: true }),
  text('queue_id', 'queue_id', (e) => e.queue_id ?? e.id, 124, { sort: 'queue_id', mono: true }),
  text('from', 'mail_from', (e) => e.mail_from, 192, { sort: 'mail_from' }),
  {
    id: 'to',
    width: 204,
    sort: 'mail_to',
    filter: 'mail_to',
    render: (e, c) => {
      const rs = recipientsOf(e);
      if (!rs.length) return null;
      return (
        <span className="cell-split">
          <V ctx={c} field="mail_to" value={rs[0].to} />
          {rs.length > 1 ? (
            <More n={rs.length - 1} title={rs.map((r) => r.to).join('\n')} />
          ) : isMultiple(e) ? (
            <span className="more" title={c.t('table.multipleRecipients')}>
              +
            </span>
          ) : null}
        </span>
      );
    },
    exportValue: (e) => recipientsOf(e).map((r) => r.to).join(', '),
  },
  text('subject', 'subject', (e) => e.subject, 220, { sort: 'subject' }),
  {
    id: 'status',
    width: 108,
    filter: 'status.message',
    render: (e, c) => (
      <span
        className="cv cv-badge"
        title={`${c.t(`status.${statusKey(e.status?.code)}`)}${e.status?.message ? `\n${e.status.message}` : ''}`}
        onClick={(ev) => {
          ev.stopPropagation();
          c.addFilter('status.code', statusKey(e.status?.code), 'eq');
        }}
      >
        <StatusBadge code={e.status?.code} compact title="" />
      </span>
    ),
    exportValue: (e) => e.status?.code ?? '',
  },
  {
    id: 'status_message',
    width: 280,
    filter: 'status.message',
    render: (e) => <span className="muted-2">{e.status?.message ?? ''}</span>,
    exportValue: (e) => e.status?.message ?? '',
  },
  {
    id: 'relay',
    width: 250,
    filter: 'relay',
    render: (e, c) => {
      const rs = relaysOf(e);
      if (!rs.length) return null;
      return (
        <span className="cell-split">
          <V ctx={c} field="relay" value={relayKey(rs[0])}>
            <RelayText r={rs[0]} />
          </V>
          <More n={rs.length - 1} title={rs.map(formatRelay).join('\n')} />
        </span>
      );
    },
    exportValue: (e) => relaysOf(e).map(formatRelay).join(', '),
  },
  {
    id: 'client',
    width: 196,
    filter: 'client',
    render: (e, c) =>
      e.client && (e.client.host || e.client.ip) ? (
        <V ctx={c} field="client" value={clientKey(e.client)}>
          <RelayText r={e.client} />
        </V>
      ) : null,
    exportValue: (e) => (e.client ? `${e.client.host ?? ''}${e.client.ip ? ` [${e.client.ip}]` : ''}` : ''),
  },
  text('sasl', 'sasl_username', (e) => e.sasl_username, 180, { sort: 'sasl_username' }),
  {
    id: 'size',
    width: 76,
    sort: 'size',
    filter: 'size',
    align: 'right',
    render: (e) => formatSize(e.size),
    exportValue: (e) => (e.size === null || e.size === undefined || e.size === '' ? null : Number(e.size)),
  },
  text('dsn', 'dsn', (e) => e.dsn, 70, { sort: 'dsn', mono: true }),
  {
    id: 'delay',
    width: 76,
    sort: 'delay',
    align: 'right',
    render: (e) => <span title={e.delay !== null && e.delay !== undefined ? `${e.delay} s` : undefined}>{formatDelay(e.delay)}</span>,
    exportValue: (e) => e.delay ?? null,
  },
  text('message_id', 'message_id', (e) => e.message_id, 260, { sort: 'message_id', mono: true }),
  text('service', 'service', (e) => e.service, 100, { sort: 'service', mono: true }),
  {
    id: 'nrcpt',
    width: 64,
    sort: 'nrcpt',
    align: 'right',
    render: (e) => e.nrcpt ?? '',
    exportValue: (e) => e.nrcpt ?? null,
  },
  {
    id: 'dkim',
    width: 150,
    filter: 'dkim.domain',
    render: (e, c) =>
      e.dkim?.domain ? (
        <>
          <V ctx={c} field="dkim.domain" value={e.dkim.domain} />
          {e.dkim.selector && <span className="muted-3 mono"> s={e.dkim.selector}</span>}
        </>
      ) : null,
    exportValue: (e) => (e.dkim?.domain ? `${e.dkim.domain}${e.dkim.selector ? ` (s=${e.dkim.selector})` : ''}` : ''),
  },
  {
    id: 'tls',
    width: 60,
    render: (e, c) =>
      e.tls === true ? (
        <span className="tls tls-on" title={c.t('detail.tlsYes')}>
          <Lock size={13} aria-hidden="true" /> TLS
        </span>
      ) : e.tls === false ? (
        <span className="tls tls-off" title={c.t('detail.tlsNo')}>
          <LockOpen size={13} aria-hidden="true" /> —
        </span>
      ) : null,
    exportValue: (e) => (e.tls === true ? 'TLS' : e.tls === false ? 'no' : ''),
  },
  time('first_attempt', 'first_attempt'),
  time('last_attempt', 'last_attempt'),
];

export const COLUMN_MAP: Record<string, ColumnDef> = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
export const ALL_COLUMN_IDS = COLUMNS.map((c) => c.id);

/** Visible columns from prefs, dropping unknown ids. */
export function visibleColumns(ids: string[]): ColumnDef[] {
  const out = ids.map((id) => COLUMN_MAP[id]).filter(Boolean);
  return out.length ? out : [COLUMN_MAP.time];
}
