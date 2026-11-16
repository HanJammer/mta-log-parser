import { useTranslation } from 'react-i18next';
import { RotateCcw, X } from 'lucide-react';
import { emptyFilters, withoutTextFilter, type Filters } from '../../lib/filters';
import { formatTime } from '../../lib/format';
import { usePrefs } from '../../lib/prefs';
import { Button } from '../../ui/primitives';
import { fieldLabel, OP_GLYPH } from './FilterBar';

type SetFilters = (f: Filters | ((f: Filters) => Filters)) => void;

function Chip({ label, op, value, onRemove, removeLabel, mono }: { label: string; op?: string; value: string; onRemove: () => void; removeLabel: string; mono?: boolean }) {
  return (
    <span className="fchip">
      <span className="fchip-field">{label}</span>
      {op && <span className="fchip-op" aria-hidden="true">{op}</span>}
      <span className={mono ? 'fchip-value mono' : 'fchip-value'} title={value}>
        {value}
      </span>
      <button type="button" className="fchip-x" onClick={onRemove} aria-label={removeLabel}>
        <X size={13} />
      </button>
    </span>
  );
}

/** Removable chips for every active filter, plus "Reset filters". */
export function ActiveFilters({ filters, setFilters, hint }: { filters: Filters; setFilters: SetFilters; hint?: boolean }) {
  const { t } = useTranslation();
  const { defaultRange, timeZone } = usePrefs();
  const chips = [];
  const rm = (label: string, value: string) => t('filters.remove', { label, value });

  if (filters.range === 'custom') {
    const v = `${filters.from ? formatTime(filters.from, timeZone, false) : '…'} – ${filters.to ? formatTime(filters.to, timeZone, false) : t('range.now')}`;
    chips.push(
      <Chip key="range" label={t('range.label')} value={v} mono onRemove={() => setFilters((f) => ({ ...f, range: defaultRange, from: undefined, to: undefined }))} removeLabel={rm(t('range.label'), v)} />,
    );
  }
  if (filters.statuses.length) {
    const v = filters.statuses.map((s) => t(`status.${s}`, { defaultValue: s })).join(', ');
    chips.push(<Chip key="st" label={t('field.status_code')} op="=" value={v} onRemove={() => setFilters((f) => ({ ...f, statuses: [] }))} removeLabel={rm(t('field.status_code'), v)} />);
  }
  if (filters.hosts.length) {
    const v = filters.hosts.join(', ');
    chips.push(<Chip key="hosts" label={t('field.host')} op="=" value={v} mono onRemove={() => setFilters((f) => ({ ...f, hosts: [] }))} removeLabel={rm(t('field.host'), v)} />);
  }
  for (const f of filters.text) {
    const label = fieldLabel(t, f.field);
    chips.push(
      <Chip
        key={`${f.field}:${f.op}`}
        label={label}
        op={OP_GLYPH[f.op]}
        value={f.value}
        onRemove={() => setFilters((x) => withoutTextFilter(x, f.field, f.op))}
        removeLabel={rm(label, f.value)}
      />,
    );
  }
  if (filters.multiple) {
    const v = filters.multiple === 'true' ? t('recipients.multiple') : t('recipients.single');
    chips.push(<Chip key="multi" label={t('recipients.title')} op="=" value={v} onRemove={() => setFilters((f) => ({ ...f, multiple: undefined }))} removeLabel={rm(t('recipients.title'), v)} />);
  }
  if (filters.logSearch) {
    chips.push(
      <Chip key="log" label={t('field.log_lines')} op={OP_GLYPH.contains} value={filters.logSearch} mono onRemove={() => setFilters((f) => ({ ...f, logSearch: '' }))} removeLabel={rm(t('field.log_lines'), filters.logSearch)} />,
    );
  }
  const dirty = chips.length > 0 || filters.range !== defaultRange;
  if (!dirty)
    return hint ? (
      <div className="active-filters is-empty">
        <span className="muted-3">{t('filters.none')}</span>
      </div>
    ) : null;
  return (
    <div className="active-filters" aria-label={t('filters.active')}>
      {chips}
      <Button variant="ghost" size="sm" icon={<RotateCcw size={13} />} onClick={() => setFilters(emptyFilters(defaultRange))}>
        {t('filters.reset')}
      </Button>
    </div>
  );
}
