import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSpreadsheet, Link2 } from 'lucide-react';
import type { Email } from '../../api/types';
import type { ColumnDef } from '../../lib/columns';
import { exportFilename, fetchAll, writeWorkbook, type ExportProgress } from '../../lib/export';
import { toSearchParams, type ListState } from '../../lib/filters';
import { copyText } from '../../lib/clipboard';
import { setPrefs, usePrefs } from '../../lib/prefs';
import { Button, Spinner } from '../../ui/primitives';
import { Popover } from '../../ui/overlays';
import { toast } from '../../ui/toast';

interface Props {
  state: ListState;
  pageRows: Email[];
  count: number;
  columns: ColumnDef[];
  maxLimit: number;
}

export function ExportMenu({ state, pageRows, count, columns, maxLimit }: Props) {
  const { t, i18n } = useTranslation();
  const prefs = usePrefs();
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState<ExportProgress | null>(null);
  const abort = useRef<AbortController | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);
  const nf = new Intl.NumberFormat(i18n.language);

  const run = async (scope: 'page' | 'all') => {
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      let rows = pageRows;
      if (scope === 'all') {
        setProgress({ loaded: 0, total: count });
        rows = await fetchAll(state, maxLimit, setProgress, ctrl.signal);
        if (ctrl.signal.aborted) return;
      }
      await writeWorkbook({
        rows,
        columns,
        tz: prefs.timeZone,
        t,
        recipientsSheet: prefs.exportRecipients,
        filename: exportFilename(state, prefs.timeZone, scope),
      });
      toast('success', t('export.done', { count: rows.length, n: nf.format(rows.length) }));
      setOpen(false);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) toast('error', t('export.failed', { message: err instanceof Error ? err.message : String(err) }));
    } finally {
      setProgress(null);
      abort.current = null;
    }
  };

  const pct = progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : 0;

  return (
    <>
      <Button ref={anchor} icon={<FileSpreadsheet size={16} />} onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} title={t('export.title')}>
        <span className="hide-sm">{t('export.button')}</span>
      </Button>
      <Popover open={open} onClose={() => !progress && setOpen(false)} anchor={anchor} align="end" label={t('export.title')} className="export-pop">
        {progress ? (
          <div className="export-progress" role="status">
            <div className="export-progress-row">
              <Spinner size={14} />
              <span>{t('export.loading', { loaded: nf.format(progress.loaded), total: nf.format(progress.total) })}</span>
            </div>
            <div className="progress">
              <div className="progress-bar" style={{ width: `${pct}%` }} />
            </div>
            <Button size="sm" onClick={() => abort.current?.abort()}>
              {t('common.cancel')}
            </Button>
          </div>
        ) : (
          <div className="menu">
            <div className="menu-note">{t('export.note', { n: columns.length })}</div>
            <button type="button" className="menu-item menu-item-2" onClick={() => void run('page')} disabled={!pageRows.length} data-autofocus>
              <span>{t('export.page')}</span>
              <span className="muted-3">{t('export.rows', { count: pageRows.length, n: nf.format(pageRows.length) })}</span>
            </button>
            <button type="button" className="menu-item menu-item-2" onClick={() => void run('all')} disabled={!count}>
              <span>{t('export.all')}</span>
              <span className="muted-3">
                {t('export.rows', { count, n: nf.format(count) })}
                {count > maxLimit ? `, ${t('export.requests', { n: Math.ceil(count / maxLimit) })}` : ''}
              </span>
            </button>
            <label className="menu-item menu-check">
              <input type="checkbox" checked={prefs.exportRecipients} onChange={(e) => setPrefs({ exportRecipients: e.target.checked })} />
              <span>{t('export.recipientsSheet')}</span>
            </label>
          </div>
        )}
      </Popover>
    </>
  );
}

/** Copies a link to the current view; relative ranges become absolute so the receiver sees the same rows. */
export function ShareButton({ state }: { state: ListState }) {
  const { t } = useTranslation();
  const { defaultRange } = usePrefs();
  const share = async () => {
    const qs = toSearchParams({ ...state, msg: state.msg }, { defaultRange, absolute: true }).toString();
    const url = `${window.location.origin}${window.location.pathname}${qs ? `?${qs}` : ''}`;
    const ok = await copyText(url);
    if (ok) toast('success', t('share.copied'));
    else toast('warning', t('share.manual'), { detail: url, ms: 20000 });
  };
  return (
    <Button icon={<Link2 size={16} />} onClick={() => void share()} title={t('share.title')}>
      <span className="hide-sm">{t('share.button')}</span>
    </Button>
  );
}
