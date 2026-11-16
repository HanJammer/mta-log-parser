/**
 * Excel export (SheetJS, write path only; the library is loaded on demand).
 * Sheet 1: visible columns in visible order. Sheet 2 (optional): one row per recipient delivery.
 */
import { api } from '../api/client';
import { emailsQuery } from '../api/hooks';
import type { Email, EmailList } from '../api/types';
import type { ColumnDef } from './columns';
import { resolveRange, type ListState } from './filters';
import { formatRelay, recipientsOf, relaysOf, wallClockDate } from './format';
import type { TimeZonePref } from './prefs';

type T = TFunction;
import type { TFunction } from 'i18next';

export interface ExportProgress {
  loaded: number;
  total: number;
}

/** Fetches every matching message, page by page with `limit = max_limit`. */
export async function fetchAll(
  state: ListState,
  maxLimit: number,
  onProgress: (p: ExportProgress) => void,
  signal: AbortSignal,
): Promise<Email[]> {
  const now = Date.now(); // one anchor for all pages, so a relative range does not drift
  const out: Email[] = [];
  let page = 1;
  let totalPages = 1;
  do {
    const res = await api.get<EmailList>('/emails', emailsQuery({ ...state, page }, maxLimit, now), signal);
    out.push(...res.result);
    totalPages = res.total_pages || 1;
    onProgress({ loaded: out.length, total: res.count });
    page += 1;
  } while (page <= totalPages && !signal.aborted);
  return out;
}

function stamp(iso: string | undefined, tz: TimeZonePref): string {
  const d = wallClockDate(iso ?? new Date().toISOString(), tz) ?? new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

export function exportFilename(state: ListState, tz: TimeZonePref, scope: 'page' | 'all'): string {
  const r = resolveRange(state.filters);
  const from = r.gt ? stamp(r.gt, tz) : 'start';
  const to = stamp(r.lt, tz);
  const suffix = scope === 'page' ? `_p${state.page}` : '';
  return `mta-log_${from}_to_${to}${suffix}.xlsx`;
}

export async function writeWorkbook(opts: {
  rows: Email[];
  columns: ColumnDef[];
  tz: TimeZonePref;
  t: T;
  recipientsSheet: boolean;
  filename: string;
}) {
  const XLSX = await import('xlsx');
  const { rows, columns, tz, t } = opts;
  const dateFmt = 'yyyy-mm-dd hh:mm:ss';

  const header = columns.map((c) => t(`col.${c.id}`));
  const data = rows.map((e) => columns.map((c) => c.exportValue(e, tz)));
  const ws = XLSX.utils.aoa_to_sheet([header, ...data], { cellDates: true, dateNF: dateFmt });
  ws['!cols'] = columns.map((c) => ({ wch: Math.max(8, Math.min(60, Math.round(c.width / 7))) }));
  if (rows.length) ws['!autofilter'] = { ref: XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: rows.length, c: columns.length - 1 } }) };

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, t('export.sheetMessages').slice(0, 31));

  if (opts.recipientsSheet) {
    const rh = [
      t('col.time'),
      t('col.host'),
      t('col.queue_id'),
      t('col.from'),
      t('detail.rcptTo'),
      t('detail.rcptOrigTo'),
      t('col.status'),
      t('col.status_message'),
      t('col.relay'),
      t('col.dsn'),
      t('col.delay'),
      t('detail.rcptTime'),
      t('detail.hiddenRecipient'),
    ];
    const rr: Array<Array<string | number | Date | null>> = [];
    for (const e of rows) {
      const recips = recipientsOf(e, true);
      const fallbackRelay = relaysOf(e)[0];
      for (const r of recips) {
        rr.push([
          wallClockDate(e.timestamp, tz),
          e.host ?? '',
          e.queue_id ?? e.id,
          e.mail_from ?? '',
          r.to,
          r.orig_to ?? '',
          r.status?.code ?? e.status?.code ?? '',
          r.status?.message ?? '',
          formatRelay(r.relay ?? (recips.length === 1 ? fallbackRelay : null)),
          r.dsn ?? '',
          r.delay ?? null,
          wallClockDate(r.timestamp, tz),
          r.hidden ? t('detail.hiddenRecipient') : '',
        ]);
      }
    }
    const ws2 = XLSX.utils.aoa_to_sheet([rh, ...rr], { cellDates: true, dateNF: dateFmt });
    ws2['!cols'] = [22, 10, 14, 30, 30, 26, 10, 60, 36, 8, 8, 22, 10].map((wch) => ({ wch }));
    if (rr.length) ws2['!autofilter'] = { ref: XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: rr.length, c: rh.length - 1 } }) };
    XLSX.utils.book_append_sheet(wb, ws2, t('export.sheetRecipients').slice(0, 31));
  }

  XLSX.writeFile(wb, opts.filename, { compression: true, cellDates: true });
}
