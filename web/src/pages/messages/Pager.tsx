import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { setPrefs, usePrefs } from '../../lib/prefs';
import { Button, Select, cx } from '../../ui/primitives';
import { PAGE_SIZES, REFRESH_OPTIONS, refreshLabel } from '../../shell/SettingsDialog';

interface Props {
  page: number;
  totalPages: number;
  count: number;
  limit: number;
  maxLimit: number;
  defaultLimit: number;
  onPage: (p: number) => void;
  onRefresh: () => void;
  fetching: boolean;
  updatedAt: number;
}

export function Pager({ page, totalPages, count, limit, maxLimit, defaultLimit, onPage, onRefresh, fetching, updatedAt }: Props) {
  const { t, i18n } = useTranslation();
  const prefs = usePrefs();
  const nf = new Intl.NumberFormat(i18n.language);
  const [input, setInput] = useState(String(page));
  useEffect(() => setInput(String(page)), [page]);
  const first = count === 0 ? 0 : (page - 1) * limit + 1;
  const last = Math.min(count, page * limit);
  const sizes = [...new Set([defaultLimit, ...PAGE_SIZES])].filter((n) => n <= maxLimit).sort((a, b) => a - b);
  const go = (p: number) => onPage(Math.min(Math.max(1, p), Math.max(1, totalPages)));
  const updated = updatedAt ? new Date(updatedAt).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

  return (
    <div className="pager">
      <div className="pager-count">
        {t('pager.range', { first: nf.format(first), last: nf.format(last), total: nf.format(count) })}
      </div>
      <div className="pager-nav" role="navigation" aria-label={t('pager.label')}>
        <Button size="sm" variant="ghost" icon={<ChevronFirst size={16} />} disabled={page <= 1} onClick={() => go(1)} aria-label={t('pager.first')} title={t('pager.first')} />
        <Button size="sm" variant="ghost" icon={<ChevronLeft size={16} />} disabled={page <= 1} onClick={() => go(page - 1)} aria-label={t('pager.previous')} title={t('pager.previous')} />
        <form
          className="pager-page"
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number.parseInt(input, 10);
            if (Number.isFinite(n)) go(n);
          }}
        >
          <input
            className="input pager-input"
            value={input}
            onChange={(e) => setInput(e.target.value.replace(/[^0-9]/g, ''))}
            onBlur={() => setInput(String(page))}
            inputMode="numeric"
            aria-label={t('pager.page')}
          />
          <span className="muted-3">{t('pager.of', { n: nf.format(Math.max(1, totalPages)) })}</span>
        </form>
        <Button size="sm" variant="ghost" icon={<ChevronRight size={16} />} disabled={page >= totalPages} onClick={() => go(page + 1)} aria-label={t('pager.next')} title={t('pager.next')} />
        <Button size="sm" variant="ghost" icon={<ChevronLast size={16} />} disabled={page >= totalPages} onClick={() => go(totalPages)} aria-label={t('pager.last')} title={t('pager.last')} />
      </div>
      <div className="pager-tools">
        <label className="pager-select">
          <span className="hide-sm">{t('pager.perPage')}</span>
          <Select value={limit} onChange={(e) => setPrefs({ pageSize: Number(e.target.value) === defaultLimit ? 0 : Number(e.target.value) })} aria-label={t('pager.perPage')}>
            {sizes.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </label>
        <label className="pager-select">
          <span className="hide-sm">{t('pager.autoRefresh')}</span>
          <Select value={prefs.refresh} onChange={(e) => setPrefs({ refresh: Number(e.target.value) })} aria-label={t('pager.autoRefresh')}>
            {REFRESH_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {refreshLabel(t, s)}
              </option>
            ))}
          </Select>
        </label>
        <Button size="sm" icon={<RefreshCw size={14} className={cx(fetching && 'spin')} />} onClick={onRefresh} title={updated ? t('pager.updated', { time: updated }) : undefined}>
          <span className="hide-sm">{t('pager.refresh')}</span>
        </Button>
        {updated && <span className="pager-updated muted-3 hide-md mono">{updated}</span>}
      </div>
    </div>
  );
}
