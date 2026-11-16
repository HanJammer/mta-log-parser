import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { EyeOff, RotateCcw, X } from 'lucide-react';
import { useByHost, useSession, useStatusCount, useTimeline, useTopRecipients, useTopRelays, useTopSenders } from '../../api/hooks';
import { STATUS_CODES, type HostStats } from '../../api/types';
import { toSearchParams, withTextFilter, type Filters, type TextField } from '../../lib/filters';
import { setPrefs, usePrefs } from '../../lib/prefs';
import { useListState } from '../../lib/useListState';
import { Button, cx, Segmented, Spinner } from '../../ui/primitives';
import { StatusIcon } from '../../ui/StatusBadge';
import { ActiveFilters } from '../messages/ActiveFilters';
import { HostPicker, LogSearch, RangePicker, RecipientsPicker, StatusChips } from '../messages/FilterBar';
import { Timeline } from './Timeline';

export const SERIES = ['sent', 'deferred', 'bounced', 'reject', 'other'] as const;
export type Series = (typeof SERIES)[number];

export function Panel({ title, sub, children, tools, className }: { title: string; sub?: ReactNode; children: ReactNode; tools?: ReactNode; className?: string }) {
  return (
    <section className={cx('panel', className)}>
      <header className="panel-head">
        <div>
          <h2>{title}</h2>
          {sub && <p className="panel-sub">{sub}</p>}
        </div>
        {tools && <div className="panel-tools">{tools}</div>}
      </header>
      {children}
    </section>
  );
}

function Loading() {
  const { t } = useTranslation();
  return (
    <div className="panel-loading">
      <Spinner size={16} label={t('common.loading')} />
    </div>
  );
}

function OverallTile({ code }: { code: string }) {
  const { t, i18n } = useTranslation();
  const q = useStatusCount(code);
  const n = q.data?.[code];
  // legacy-only status: hide the tile when no old documents carry it
  if (code === 'multiple' && !n) return null;
  return (
    <div className={cx('tile', `st-${code}`)}>
      <div className="tile-label">
        <StatusIcon code={code} size={14} />
        <span>{t(`status.${code}`)}</span>
      </div>
      <div className="tile-value">{q.isPending ? '…' : n === undefined ? '—' : new Intl.NumberFormat(i18n.language).format(n)}</div>
    </div>
  );
}

function sumHosts(rows: HostStats[] | undefined): Record<Series, number> & { count: number } {
  const s = { sent: 0, deferred: 0, bounced: 0, reject: 0, other: 0, count: 0 };
  for (const r of rows ?? []) {
    s.sent += r.sent ?? 0;
    s.deferred += r.deferred ?? 0;
    s.bounced += r.bounced ?? 0;
    s.reject += r.reject ?? 0;
    s.count += r.count ?? 0;
  }
  s.other = Math.max(0, s.count - s.sent - s.deferred - s.bounced - s.reject);
  return s;
}

/** One 100 % bar, segments separated by 2px gaps, legend with counts below. */
function StackBar({ values, total, compact }: { values: Record<Series, number>; total: number; compact?: boolean }) {
  const { t, i18n } = useTranslation();
  const nf = new Intl.NumberFormat(i18n.language);
  const pf = new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 });
  const label = (s: Series) => (s === 'other' ? t('stats.other') : t(`status.${s}`));
  return (
    <div className={cx('stackbar', compact && 'is-compact')}>
      <div className="stackbar-track" role="img" aria-label={SERIES.map((s) => `${label(s)}: ${nf.format(values[s])}`).join(', ')}>
        {total > 0 &&
          SERIES.filter((s) => values[s] > 0).map((s) => (
            <div key={s} className={`stackbar-seg seg-${s}`} style={{ flexGrow: values[s] }} title={`${label(s)}: ${nf.format(values[s])} (${pf.format(values[s] / total)})`} />
          ))}
      </div>
      {!compact && (
        <ul className="legend">
          {SERIES.map((s) => (
            <li key={s} className={values[s] === 0 ? 'is-zero' : undefined}>
              <span className={`legend-swatch seg-${s}`} aria-hidden="true" />
              {s !== 'other' && <StatusIcon code={s} size={13} />}
              <span className="legend-label">{label(s)}</span>
              <span className="legend-value">{nf.format(values[s])}</span>
              <span className="legend-pct">{total ? pf.format(values[s] / total) : '—'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type TopKind = 'senders' | 'recipients' | 'relays';

function TopList({
  kind,
  items,
  loading,
  field,
  onFilter,
  configHidden,
}: {
  kind: TopKind;
  items: Array<{ key: string; count: number }>;
  loading: boolean;
  field: TextField;
  onFilter: (field: TextField, value: string) => void;
  configHidden: string[];
}) {
  const { t, i18n } = useTranslation();
  const prefs = usePrefs();
  const hidden = prefs.hiddenTop[kind];
  const nf = new Intl.NumberFormat(i18n.language);
  const shown = items.filter((i) => i.key && !hidden.includes(i.key));
  const max = Math.max(1, ...shown.map((i) => i.count));
  const setHidden = (list: string[]) => setPrefs((p) => ({ hiddenTop: { ...p.hiddenTop, [kind]: list } }));

  return (
    <Panel title={t(`stats.top.${kind}`)} sub={configHidden.length ? t('stats.serverHidden', { list: configHidden.join(', ') }) : undefined} className="panel-top">
      {loading ? (
        <Loading />
      ) : shown.length === 0 ? (
        <p className="muted-3 panel-empty">{t('stats.noData')}</p>
      ) : (
        <ol className="toplist">
          {shown.map((i) => (
            <li key={i.key} className="toprow">
              <button type="button" className="toprow-label" onClick={() => onFilter(field, i.key)} title={t('stats.showMessages', { value: i.key })}>
                {i.key}
              </button>
              <span className="toprow-bar" aria-hidden="true">
                <span style={{ width: `${(i.count / max) * 100}%` }} />
              </span>
              <span className="toprow-count">{nf.format(i.count)}</span>
              <button type="button" className="mini-btn toprow-hide" onClick={() => setHidden([...hidden, i.key])} title={t('stats.hide')} aria-label={`${t('stats.hide')}: ${i.key}`}>
                <EyeOff size={13} />
              </button>
            </li>
          ))}
        </ol>
      )}
      {hidden.length > 0 && (
        <div className="hidden-items">
          <span className="muted-3">{t('stats.hidden')}</span>
          {hidden.map((h) => (
            <span key={h} className="fchip fchip-sm">
              <span className="fchip-value" title={h}>
                {h}
              </span>
              <button type="button" className="fchip-x" onClick={() => setHidden(hidden.filter((x) => x !== h))} aria-label={`${t('stats.unhide')}: ${h}`}>
                <X size={12} />
              </button>
            </span>
          ))}
          <button type="button" className="linkish" onClick={() => setHidden([])}>
            {t('stats.unhideAll')}
          </button>
        </div>
      )}
    </Panel>
  );
}

function autoBucket(f: Filters): 'hour' | 'day' {
  if (f.range === '1h' || f.range === '24h') return 'hour';
  if (f.range === 'custom' && f.from) {
    const span = (f.to ? new Date(f.to).getTime() : Date.now()) - new Date(f.from).getTime();
    return span <= 3 * 24 * 3600e3 ? 'hour' : 'day';
  }
  return 'day';
}

export function StatsPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { state, setFilters } = useListState();
  const { defaultRange } = usePrefs();
  const config = useSession().data?.config ?? {};
  const f = state.filters;
  const [bucketPref, setBucketPref] = useState<'auto' | 'hour' | 'day'>('auto');
  const bucket = bucketPref === 'auto' ? autoBucket(f) : bucketPref;

  const byHost = useByHost(f);
  const timeline = useTimeline(f, bucket);
  const senders = useTopSenders(f);
  const recipients = useTopRecipients(f);
  const relays = useTopRelays(f);
  const totals = useMemo(() => sumHosts(byHost.data), [byHost.data]);
  const nf = new Intl.NumberFormat(i18n.language);

  useEffect(() => {
    document.title = `${t('nav.stats')} · ${t('app.title')}`;
  }, [t]);

  const toMessages = (field: TextField, value: string) => {
    const next = withTextFilter(f, { field, op: 'eq', value });
    const qs = toSearchParams({ filters: next, page: 1, order: state.order, dir: state.dir }, { defaultRange }).toString();
    navigate({ pathname: '/', search: qs ? `?${qs}` : '' });
  };

  const hostRows = byHost.data ?? [];

  return (
    <div className="page-stats">
      <section className="filterbar" aria-label={t('filters.title')}>
        <div className="filterbar-row">
          <RangePicker filters={f} setFilters={setFilters} />
          <HostPicker filters={f} setFilters={setFilters} />
          <RecipientsPicker filters={f} setFilters={setFilters} />
          <StatusChips filters={f} setFilters={setFilters} />
          <LogSearch filters={f} setFilters={setFilters} />
        </div>
        <ActiveFilters filters={f} setFilters={setFilters} />
      </section>

      <div className="stats">
        <Panel
          title={t('stats.overall')}
          sub={config.housekeeping_days ? t('stats.overallSubDays', { n: config.housekeeping_days }) : t('stats.overallSub')}
          className="panel-overall"
        >
          <div className="tiles">
            {STATUS_CODES.map((c) => (
              <OverallTile key={c} code={c} />
            ))}
          </div>
        </Panel>

        <Panel
          title={t('stats.filtered')}
          sub={byHost.data ? t('stats.filteredSub', { count: totals.count, n: nf.format(totals.count) }) : undefined}
          className="panel-dist"
        >
          {byHost.isPending ? <Loading /> : byHost.isError ? <p className="error-text">{byHost.error.message}</p> : <StackBar values={totals} total={totals.count} />}
        </Panel>

        <Panel
          title={t('stats.timeline')}
          className="panel-timeline"
          tools={
            <Segmented<'auto' | 'hour' | 'day'>
              label={t('stats.bucket')}
              value={bucketPref}
              onChange={setBucketPref}
              options={[
                { value: 'auto', label: t('stats.bucketAuto') },
                { value: 'hour', label: t('stats.bucketHour') },
                { value: 'day', label: t('stats.bucketDay') },
              ]}
            />
          }
        >
          {timeline.isPending ? <Loading /> : timeline.isError ? <p className="error-text">{timeline.error.message}</p> : <Timeline points={timeline.data} bucket={bucket} />}
        </Panel>

        <Panel title={t('stats.byHost')} className="panel-hosts">
          {byHost.isPending ? (
            <Loading />
          ) : hostRows.length === 0 ? (
            <p className="muted-3 panel-empty">{t('stats.noData')}</p>
          ) : (
            <table className="htable">
              <thead>
                <tr>
                  <th>{t('col.host')}</th>
                  <th className="is-right">{t('stats.total')}</th>
                  <th className="htable-bar">{t('stats.split')}</th>
                  {(['sent', 'deferred', 'bounced', 'reject'] as const).map((s) => (
                    <th key={s} className="is-right">
                      <span className="th-status">
                        <StatusIcon code={s} size={12} />
                        <span className="hide-md">{t(`status.${s}`)}</span>
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hostRows.map((h) => {
                  const other = Math.max(0, h.count - h.sent - h.deferred - h.bounced - h.reject);
                  return (
                    <tr key={h.host}>
                      <td>
                        <button type="button" className="linkish mono" onClick={() => toMessages('host', h.host)} title={t('stats.showMessages', { value: h.host })}>
                          {h.host || '—'}
                        </button>
                      </td>
                      <td className="is-right strong">{nf.format(h.count)}</td>
                      <td className="htable-bar">
                        <StackBar compact values={{ sent: h.sent, deferred: h.deferred, bounced: h.bounced, reject: h.reject, other }} total={h.count} />
                      </td>
                      <td className="is-right">{nf.format(h.sent)}</td>
                      <td className="is-right">{nf.format(h.deferred)}</td>
                      <td className="is-right">{nf.format(h.bounced)}</td>
                      <td className="is-right">{nf.format(h.reject)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Panel>

        <div className="tops">
          <TopList
            kind="senders"
            field="mail_from"
            loading={senders.isPending}
            items={(senders.data ?? []).map((x) => ({ key: x.mail_from, count: x.count }))}
            onFilter={toMessages}
            configHidden={config.exclude_from_top_senders ?? []}
          />
          <TopList
            kind="recipients"
            field="mail_to"
            loading={recipients.isPending}
            items={(recipients.data ?? []).map((x) => ({ key: x.mail_to, count: x.count }))}
            onFilter={toMessages}
            configHidden={config.exclude_from_top_recipients ?? []}
          />
          <TopList
            kind="relays"
            field="relay"
            loading={relays.isPending}
            items={(relays.data ?? []).map((x) => ({ key: x.relay, count: x.count }))}
            onFilter={toMessages}
            configHidden={[]}
          />
        </div>
      </div>
      <div className="stats-foot">
        <Button variant="ghost" size="sm" icon={<RotateCcw size={13} />} onClick={() => setPrefs({ hiddenTop: { senders: [], recipients: [], relays: [] } })}>
          {t('stats.unhideAllLists')}
        </Button>
      </div>
    </div>
  );
}
