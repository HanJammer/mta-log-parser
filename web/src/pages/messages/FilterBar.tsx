import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarRange, ChevronDown, FileSearch, Server, TriangleAlert, Users, X } from 'lucide-react';
import { useFacets } from '../../api/hooks';
import { STATUS_CODES } from '../../api/types';
import { RANGE_PRESETS, type Filters, type Op, type RangePreset } from '../../lib/filters';
import { formatTime } from '../../lib/format';
import { usePrefs, type TimeZonePref } from '../../lib/prefs';
import { Button, cx, Input, Segmented } from '../../ui/primitives';
import { Popover } from '../../ui/overlays';
import { StatusIcon } from '../../ui/StatusBadge';
import { toast } from '../../ui/toast';

type SetFilters = (f: Filters | ((f: Filters) => Filters)) => void;

export function fieldLabel(t: (k: string) => string, field: string): string {
  return t(`field.${field.replace(/\./g, '_')}`);
}

export const OP_GLYPH: Record<Op, string> = { contains: '∋', not: '∌', eq: '=' };

/** Time range: quick presets plus a custom from/to popover. */
export function RangePicker({ filters, setFilters }: { filters: Filters; setFilters: SetFilters }) {
  const { t } = useTranslation();
  const { timeZone } = usePrefs();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const custom = filters.range === 'custom';
  const options = RANGE_PRESETS.map((r) => ({ value: r, label: t(`range.short.${r}`), title: t(`range.long.${r}`) }));
  return (
    <div className="range">
      <Segmented<RangePreset | 'custom'>
        label={t('range.label')}
        value={filters.range}
        options={options}
        onChange={(r) => setFilters((f) => ({ ...f, range: r as RangePreset, from: undefined, to: undefined }))}
      />
      <Button
        ref={anchor}
        size="md"
        variant={custom ? 'default' : 'ghost'}
        pressed={custom}
        icon={<CalendarRange size={15} />}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cx('range-custom', custom && 'is-active')}
      >
        {custom ? (
          <span className="mono range-text">
            {filters.from ? formatTime(filters.from, timeZone, false) : '…'} – {filters.to ? formatTime(filters.to, timeZone, false) : t('range.now')}
          </span>
        ) : (
          t('range.custom')
        )}
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t('range.custom')}>
        <CustomRangeForm
          filters={filters}
          tz={timeZone}
          onApply={(from, to) => {
            setFilters((f) => ({ ...f, range: 'custom', from, to }));
            setOpen(false);
          }}
        />
      </Popover>
    </div>
  );
}

const pad = (n: number) => String(n).padStart(2, '0');

function toInput(iso: string | undefined, tz: TimeZonePref): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return tz === 'utc'
    ? `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
    : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromInput(v: string, tz: TimeZonePref): string | undefined {
  if (!v) return undefined;
  const d = new Date(tz === 'utc' ? `${v}:00Z` : v);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

function CustomRangeForm({ filters, tz, onApply }: { filters: Filters; tz: TimeZonePref; onApply: (from?: string, to?: string) => void }) {
  const { t } = useTranslation();
  const initialFrom = filters.range === 'custom' ? filters.from : new Date(Date.now() - 24 * 3600e3).toISOString();
  const [from, setFrom] = useState(toInput(initialFrom, tz));
  const [to, setTo] = useState(toInput(filters.range === 'custom' ? filters.to : undefined, tz));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onApply(fromInput(from, tz), fromInput(to, tz));
  };
  const invalid = !!from && !!to && from >= to;
  return (
    <form className="range-form" onSubmit={submit}>
      <label className="field">
        <span className="field-label">{t('range.from')}</span>
        <input className="input mono" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} data-autofocus />
      </label>
      <label className="field">
        <span className="field-label">{t('range.to')}</span>
        <input className="input mono" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
        <span className="field-hint">{t('range.toHint')}</span>
      </label>
      {!from && <p className="warn-text">{t('range.noStartWarning')}</p>}
      <div className="range-form-foot">
        <span className="muted-3">{tz === 'utc' ? 'UTC' : t('settings.tzLocal')}</span>
        <Button type="submit" variant="primary" size="sm" disabled={invalid}>
          {t('common.apply')}
        </Button>
      </div>
    </form>
  );
}

export function HostPicker({ filters, setFilters }: { filters: Filters; setFilters: SetFilters }) {
  const { t } = useTranslation();
  const facets = useFacets();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const hosts = [...new Set([...(facets.data?.hosts ?? []), ...filters.hosts])].sort();
  const sel = filters.hosts;
  const label = sel.length === 0 ? t('hosts.all') : sel.length === 1 ? sel[0] : t('hosts.n', { count: sel.length });
  const toggle = (h: string) =>
    setFilters((f) => ({ ...f, hosts: f.hosts.includes(h) ? f.hosts.filter((x) => x !== h) : [...f.hosts, h] }));
  return (
    <>
      <Button
        ref={anchor}
        icon={<Server size={15} />}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        pressed={sel.length > 0}
        className={cx('picker', sel.length > 0 && 'is-active')}
      >
        <span className={sel.length === 1 ? 'mono' : undefined}>{label}</span>
        <ChevronDown size={14} aria-hidden="true" className="picker-caret" />
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t('hosts.title')}>
        <div className="menu">
          <div className="menu-note">{t('hosts.title')}</div>
          {facets.isPending && <div className="menu-note">{t('common.loading')}</div>}
          {hosts.map((h) => (
            <label key={h} className="menu-item menu-check">
              <input type="checkbox" checked={sel.includes(h)} onChange={() => toggle(h)} />
              <span className="mono">{h}</span>
            </label>
          ))}
          {!facets.isPending && hosts.length === 0 && <div className="menu-note">{t('hosts.none')}</div>}
          {sel.length > 0 && (
            <button type="button" className="menu-item" onClick={() => setFilters((f) => ({ ...f, hosts: [] }))}>
              <X size={14} aria-hidden="true" />
              {t('hosts.clear')}
            </button>
          )}
        </div>
      </Popover>
    </>
  );
}

/** Status `multiple` exists only on legacy documents: its chip appears only when selected. */
const MAIN_STATUSES = STATUS_CODES.filter((c) => c !== 'multiple');

export function StatusChips({ filters, setFilters }: { filters: Filters; setFilters: SetFilters }) {
  const { t } = useTranslation();
  const toggle = (c: string) =>
    setFilters((f) => ({ ...f, statuses: f.statuses.includes(c) ? f.statuses.filter((x) => x !== c) : [...f.statuses, c] }));
  const codes = filters.statuses.includes('multiple') ? [...MAIN_STATUSES, 'multiple'] : MAIN_STATUSES;
  return (
    <div className="chips" role="group" aria-label={t('field.status_code')}>
      {codes.map((c) => {
        const on = filters.statuses.includes(c);
        return (
          <button key={c} type="button" className={cx('chip', `st-${c}`, on && 'is-on')} aria-pressed={on} onClick={() => toggle(c)}>
            <StatusIcon code={c} size={13} />
            <span>{t(`status.${c}`)}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Single- vs multi-recipient messages (`multiple__eq`). */
export function RecipientsPicker({ filters, setFilters }: { filters: Filters; setFilters: SetFilters }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const value = filters.multiple ?? 'any';
  const options = [
    { v: 'any', label: t('recipients.any') },
    { v: 'false', label: t('recipients.single') },
    { v: 'true', label: t('recipients.multiple') },
  ] as const;
  const current = options.find((o) => o.v === value)!;
  return (
    <>
      <Button
        ref={anchor}
        icon={<Users size={15} />}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        pressed={!!filters.multiple}
        className={cx('picker', filters.multiple && 'is-active')}
        title={t('recipients.title')}
      >
        <span>{current.label}</span>
        <ChevronDown size={14} aria-hidden="true" className="picker-caret" />
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t('recipients.title')}>
        <div className="menu" role="radiogroup" aria-label={t('recipients.title')}>
          <div className="menu-note">{t('recipients.title')}</div>
          {options.map((o) => (
            <label key={o.v} className="menu-item menu-check">
              <input
                type="radio"
                name="mlp-recipients"
                checked={value === o.v}
                onChange={() => {
                  setFilters((f) => ({ ...f, multiple: o.v === 'any' ? undefined : o.v }));
                  setOpen(false);
                }}
              />
              <span>{o.label}</span>
            </label>
          ))}
        </div>
      </Popover>
    </>
  );
}

export function LogSearch({ filters, setFilters }: { filters: Filters; setFilters: SetFilters }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(filters.logSearch);
  useEffect(() => setValue(filters.logSearch), [filters.logSearch]);
  const commit = () => {
    const v = value.trim();
    if (v === filters.logSearch) return;
    if (v) toast('warning', t('logSearch.slowToast'));
    setFilters((f) => ({ ...f, logSearch: v }));
  };
  return (
    <form
      className={cx('log-search', filters.logSearch && 'is-active')}
      onSubmit={(e) => {
        e.preventDefault();
        commit();
      }}
      role="search"
    >
      <Input
        icon={<FileSearch size={15} />}
        type="search"
        value={value}
        placeholder={t('logSearch.placeholder')}
        aria-label={t('logSearch.label')}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        title={t('logSearch.hint')}
      />
      {filters.logSearch && (
        <span className="log-search-warn" title={t('logSearch.hint')}>
          <TriangleAlert size={14} aria-hidden="true" />
          <span className="sr-only">{t('logSearch.hint')}</span>
        </span>
      )}
    </form>
  );
}
