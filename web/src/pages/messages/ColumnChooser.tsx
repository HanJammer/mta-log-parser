import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Columns3, GripVertical, RotateCcw } from 'lucide-react';
import { ALL_COLUMN_IDS } from '../../lib/columns';
import { DEFAULT_COLUMNS, setPrefs, usePrefs } from '../../lib/prefs';
import { Button, cx } from '../../ui/primitives';
import { Popover } from '../../ui/overlays';

/** Show/hide and reorder table columns (drag, or the arrow buttons for keyboard users). */
export function ColumnChooser() {
  const { t } = useTranslation();
  const { columns } = usePrefs();
  const [open, setOpen] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);
  const visible = columns.filter((c) => ALL_COLUMN_IDS.includes(c));
  const hidden = ALL_COLUMN_IDS.filter((c) => !visible.includes(c));

  const set = (next: string[]) => setPrefs({ columns: next.length ? next : ['time'] });
  const toggle = (id: string) => set(visible.includes(id) ? visible.filter((c) => c !== id) : [...visible, id]);
  const move = (id: string, delta: number) => {
    const i = visible.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= visible.length) return;
    const next = [...visible];
    [next[i], next[j]] = [next[j], next[i]];
    set(next);
  };
  const drop = (target: string) => {
    if (!dragging || dragging === target) return;
    const next = visible.filter((c) => c !== dragging);
    next.splice(next.indexOf(target), 0, dragging);
    set(next);
  };

  return (
    <>
      <Button ref={anchor} icon={<Columns3 size={16} />} onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} title={t('columns.title')}>
        <span className="hide-sm">{t('columns.button')}</span>
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} align="end" label={t('columns.title')} className="colchooser">
        <div className="colchooser-head">
          <span>{t('columns.title')}</span>
          <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={() => setPrefs({ columns: DEFAULT_COLUMNS, widths: {} })}>
            {t('columns.reset')}
          </Button>
        </div>
        <ul className="colchooser-list" aria-label={t('columns.visible')}>
          {visible.map((id, i) => (
            <li
              key={id}
              className={cx('colchooser-item', dragging === id && 'is-dragging', over === id && dragging !== id && 'is-over')}
              draggable
              onDragStart={(e) => {
                setDragging(id);
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', id);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(id);
              }}
              onDragLeave={() => setOver((o) => (o === id ? null : o))}
              onDrop={(e) => {
                e.preventDefault();
                drop(id);
                setOver(null);
              }}
              onDragEnd={() => {
                setDragging(null);
                setOver(null);
              }}
            >
              <GripVertical size={14} className="grip" aria-hidden="true" />
              <label className="colchooser-label">
                <input type="checkbox" checked onChange={() => toggle(id)} />
                <span>{t(`col.${id}`)}</span>
              </label>
              <span className="colchooser-moves">
                <button type="button" className="mini-btn" disabled={i === 0} onClick={() => move(id, -1)} aria-label={t('columns.up', { name: t(`col.${id}`) })}>
                  <ArrowUp size={13} />
                </button>
                <button type="button" className="mini-btn" disabled={i === visible.length - 1} onClick={() => move(id, 1)} aria-label={t('columns.down', { name: t(`col.${id}`) })}>
                  <ArrowDown size={13} />
                </button>
              </span>
            </li>
          ))}
        </ul>
        {hidden.length > 0 && (
          <>
            <div className="colchooser-sub">{t('columns.hidden')}</div>
            <ul className="colchooser-list">
              {hidden.map((id) => (
                <li key={id} className="colchooser-item is-hidden">
                  <span className="grip-space" />
                  <label className="colchooser-label">
                    <input type="checkbox" checked={false} onChange={() => toggle(id)} />
                    <span>{t(`col.${id}`)}</span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </Popover>
    </>
  );
}
