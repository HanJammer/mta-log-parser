import { memo, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as RPointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import type { Email } from '../../api/types';
import type { CellCtx, ColumnDef } from '../../lib/columns';
import { OPS, paramKey, type Filters, type Op, type SortDir, type TextField } from '../../lib/filters';
import { statusCode } from '../../lib/format';
import { setPrefs, usePrefs } from '../../lib/prefs';
import { cx } from '../../ui/primitives';
import { fieldLabel, OP_GLYPH } from './FilterBar';

interface Props {
  columns: ColumnDef[];
  rows: Email[];
  order: string;
  dir: SortDir;
  onSort: (order: string, dir: SortDir) => void;
  selectedId?: string;
  onOpen: (id: string) => void;
  ctx: CellCtx;
  filters: Filters;
  onColumnFilter: (field: TextField, op: Op, value: string, prevOp: Op | null) => void;
  showFilterRow: boolean;
  busy: boolean;
}

const MIN_W = 48;

export function EmailTable({ columns, rows, order, dir, onSort, selectedId, onOpen, ctx, filters, onColumnFilter, showFilterRow, busy }: Props) {
  const { t } = useTranslation();
  const prefs = usePrefs();
  const [live, setLive] = useState<Record<string, number>>({});
  const widthOf = (c: ColumnDef) => live[c.id] ?? prefs.widths[c.id] ?? c.width;
  const total = columns.reduce((s, c) => s + widthOf(c), 0);

  const startResize = (e: RPointerEvent, c: ColumnDef) => {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startW = widthOf(c);
    let w = startW;
    const move = (ev: PointerEvent) => {
      w = Math.max(MIN_W, Math.round(startW + ev.clientX - startX));
      setLive((l) => ({ ...l, [c.id]: w }));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.classList.remove('is-resizing');
      setPrefs((p) => ({ widths: { ...p.widths, [c.id]: w } }));
      setLive((l) => {
        const n = { ...l };
        delete n[c.id];
        return n;
      });
    };
    document.body.classList.add('is-resizing');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const sortBy = (c: ColumnDef) => {
    if (!c.sort) return;
    if (order === c.sort) onSort(c.sort, dir === 'asc' ? 'desc' : 'asc');
    else onSort(c.sort, c.align === 'right' || c.sort.endsWith('attempt') || c.sort === 'timestamp' ? 'desc' : 'asc');
  };

  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, id: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(id);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const sib = (e.key === 'ArrowDown' ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling) as HTMLElement | null;
      sib?.focus();
    }
  };

  return (
    <table className={cx('grid', prefs.coloredRows && 'is-colored', busy && 'is-busy')} style={{ width: total }}>
      <colgroup>
        {columns.map((c) => (
          <col key={c.id} style={{ width: widthOf(c) }} />
        ))}
      </colgroup>
      <thead>
        <tr className="grid-head">
          {columns.map((c) => {
            const active = c.sort && order === c.sort;
            const aria = active ? (dir === 'asc' ? 'ascending' : 'descending') : undefined;
            return (
              <th key={c.id} scope="col" aria-sort={aria} className={cx(c.align === 'right' && 'is-right')}>
                {c.sort ? (
                  <button type="button" className={cx('th-btn', active && 'is-sorted')} onClick={() => sortBy(c)} title={t('table.sortBy', { name: t(`col.${c.id}`) })}>
                    <span className="th-label">{t(`col.${c.id}`)}</span>
                    {active ? (
                      dir === 'asc' ? <ArrowUp size={13} aria-hidden="true" /> : <ArrowDown size={13} aria-hidden="true" />
                    ) : (
                      <ArrowUpDown size={12} aria-hidden="true" className="th-sort-idle" />
                    )}
                  </button>
                ) : (
                  <span className="th-static">
                    <span className="th-label">{t(`col.${c.id}`)}</span>
                  </span>
                )}
                <span className="th-resize" onPointerDown={(e) => startResize(e, c)} onDoubleClick={() => setPrefs((p) => {
                  const w = { ...p.widths };
                  delete w[c.id];
                  return { widths: w };
                })} aria-hidden="true" />
              </th>
            );
          })}
        </tr>
        {showFilterRow && (
          <tr className="grid-filters">
            {columns.map((c) => (
              <th key={c.id}>{c.filter ? <ColumnFilter field={c.filter} filters={filters} onChange={onColumnFilter} /> : null}</th>
            ))}
          </tr>
        )}
      </thead>
      <tbody>
        {rows.map((e) => (
          <Row key={e.id} e={e} columns={columns} selected={e.id === selectedId} onOpen={onOpen} onKey={onRowKey} ctx={ctx} />
        ))}
      </tbody>
    </table>
  );
}

const Row = memo(function Row({
  e,
  columns,
  selected,
  onOpen,
  onKey,
  ctx,
}: {
  e: Email;
  columns: ColumnDef[];
  selected: boolean;
  onOpen: (id: string) => void;
  onKey: (e: KeyboardEvent<HTMLTableRowElement>, id: string) => void;
  ctx: CellCtx;
}) {
  return (
    <tr
      className={cx('grid-row', `row-${statusCode(e.status)}`, selected && 'is-selected')}
      tabIndex={0}
      onClick={() => {
        if (window.getSelection()?.toString()) return; // let people select text without opening
        onOpen(e.id);
      }}
      onKeyDown={(ev) => onKey(ev, e.id)}
      aria-selected={selected}
      data-id={e.id}
    >
      {columns.map((c) => (
        <td key={c.id} className={cx(c.align === 'right' && 'is-right', c.mono && 'mono')}>
          <div className="cell">{c.render(e, ctx)}</div>
        </td>
      ))}
    </tr>
  );
});

function ColumnFilter({
  field,
  filters,
  onChange,
}: {
  field: TextField;
  filters: Filters;
  onChange: (field: TextField, op: Op, value: string, prevOp: Op | null) => void;
}) {
  const { t } = useTranslation();
  const current = filters.text.find((f) => f.field === field);
  const [op, setOp] = useState<Op>(current?.op ?? 'contains');
  const [value, setValue] = useState(current?.value ?? '');
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    setOp(current?.op ?? 'contains');
    setValue(current?.value ?? '');
  }, [current?.op, current?.value]);

  const commit = (nextOp: Op, nextValue: string) => {
    window.clearTimeout(timer.current);
    const v = nextValue.trim();
    if (current && current.op === nextOp && current.value === v) return;
    if (!current && !v) return;
    onChange(field, nextOp, v, current?.op ?? null);
  };

  const label = fieldLabel(t, field);
  const exists = filters.text.some((f) => paramKey(f.field, f.op) === paramKey(field, op));
  return (
    <div className={cx('colfilter', (exists || value) && 'has-value')}>
      <button
        type="button"
        className="colfilter-op"
        title={t(`ops.${op}`)}
        aria-label={`${label}: ${t(`ops.${op}`)}`}
        onClick={() => {
          const next = OPS[(OPS.indexOf(op) + 1) % OPS.length];
          setOp(next);
          if (value.trim()) commit(next, value);
        }}
      >
        {OP_GLYPH[op]}
      </button>
      <input
        className="colfilter-input"
        value={value}
        placeholder={t('table.filterPlaceholder')}
        aria-label={t('table.filterLabel', { name: label })}
        onChange={(e) => {
          const v = e.target.value;
          setValue(v);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => commit(op, v), 700);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit(op, value);
          if (e.key === 'Escape' && value) {
            e.stopPropagation();
            setValue('');
            commit(op, '');
          }
        }}
        onBlur={() => commit(op, value)}
      />
    </div>
  );
}
