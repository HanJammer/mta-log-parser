import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Filter, Inbox, RotateCcw, TriangleAlert } from 'lucide-react';
import { useEmails, useSession } from '../../api/hooks';
import { visibleColumns, type CellCtx } from '../../lib/columns';
import { emptyFilters, withTextFilter, withoutTextFilter, type Op, type TextField } from '../../lib/filters';
import { useListState } from '../../lib/useListState';
import { setPrefs, usePrefs } from '../../lib/prefs';
import { errorText } from '../../lib/errors';
import { Button, Empty, Spinner } from '../../ui/primitives';
import { ActiveFilters } from './ActiveFilters';
import { ColumnChooser } from './ColumnChooser';
import { EmailTable } from './EmailTable';
import { ExportMenu, ShareButton } from './ExportMenu';
import { HostPicker, LogSearch, RangePicker, RecipientsPicker, StatusChips } from './FilterBar';
import { MessageDrawer } from './MessageDrawer';
import { Pager } from './Pager';

export function MessagesPage() {
  const { t } = useTranslation();
  const prefs = usePrefs();
  const config = useSession().data?.config ?? {};
  const maxLimit = config.max_limit || 1000;
  const defaultLimit = Math.min(config.default_limit || 50, maxLimit);
  const limit = Math.min(prefs.pageSize || defaultLimit, maxLimit);
  const { state, update, setFilters } = useListState();
  const q = useEmails(state, limit, prefs.refresh, true);
  const rows = useMemo(() => q.data?.result ?? [], [q.data]);
  const columns = visibleColumns(prefs.columns);

  useEffect(() => {
    document.title = `${t('nav.messages')} · ${t('app.title')}`;
  }, [t]);

  // Clamp the page when the result shrinks (e.g. after a filter change on a later page).
  useEffect(() => {
    if (q.data && q.data.total_pages > 0 && state.page > q.data.total_pages) update({ page: q.data.total_pages });
  }, [q.data, state.page, update]);

  const addFilter = useCallback(
    (field: TextField, value: string, op: Op) => setFilters((f) => withTextFilter(f, { field, op, value })),
    [setFilters],
  );
  const ctx: CellCtx = useMemo(() => ({ tz: prefs.timeZone, t, addFilter }), [prefs.timeZone, t, addFilter]);

  const onColumnFilter = useCallback(
    (field: TextField, op: Op, value: string, prevOp: Op | null) =>
      setFilters((f) => {
        let next = prevOp ? withoutTextFilter(f, field, prevOp) : f;
        if (value) next = withTextFilter(next, { field, op, value });
        return next;
      }),
    [setFilters],
  );

  const open = useCallback((id: string) => update({ msg: id }, { push: true }), [update]);
  const idx = state.msg ? rows.findIndex((r) => r.id === state.msg) : -1;
  const prev = idx > 0 ? () => update({ msg: rows[idx - 1].id }) : undefined;
  const next = idx >= 0 && idx < rows.length - 1 ? () => update({ msg: rows[idx + 1].id }) : undefined;

  // keep the open row visible while stepping through messages
  useEffect(() => {
    if (!state.msg) return;
    const el = document.querySelector<HTMLElement>(`tr[data-id="${CSS.escape(state.msg)}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [state.msg]);

  const count = q.data?.count ?? 0;
  const filterRowCount = state.filters.text.length;

  return (
    <div className="page-messages">
      <section className="filterbar" aria-label={t('filters.title')}>
        <div className="filterbar-row">
          <RangePicker filters={state.filters} setFilters={setFilters} />
          <HostPicker filters={state.filters} setFilters={setFilters} />
          <RecipientsPicker filters={state.filters} setFilters={setFilters} />
          <StatusChips filters={state.filters} setFilters={setFilters} />
          <LogSearch filters={state.filters} setFilters={setFilters} />
        </div>
        <div className="filterbar-row2">
          <ActiveFilters filters={state.filters} setFilters={setFilters} hint />
          <div className="filterbar-actions">
            <Button
              icon={<Filter size={16} />}
              pressed={prefs.showFilterRow}
              onClick={() => setPrefs({ showFilterRow: !prefs.showFilterRow })}
              title={t('table.filterRowToggle')}
              badge={filterRowCount || undefined}
            >
              <span className="hide-sm">{t('table.filterRow')}</span>
            </Button>
            <ColumnChooser />
            <ExportMenu state={state} pageRows={rows} count={count} columns={columns} maxLimit={maxLimit} />
            <ShareButton state={state} />
          </div>
        </div>
      </section>

      <div className="table-region">
        {q.isFetching && <div className="loadbar" aria-hidden="true" />}
        {q.isError ? (
          <Empty icon={<TriangleAlert size={28} />} title={t('errors.loadFailed')}>
            <p>{errorText(q.error, t)}</p>
            <Button icon={<RotateCcw size={14} />} onClick={() => void q.refetch()}>
              {t('common.retry')}
            </Button>
          </Empty>
        ) : q.isPending ? (
          <div className="table-loading">
            <Spinner size={20} label={t('common.loading')} />
          </div>
        ) : (
          <div className="table-scroll" tabIndex={-1}>
            <EmailTable
              columns={columns}
              rows={rows}
              order={state.order}
              dir={state.dir}
              onSort={(order, dir) => update({ order, dir, page: 1 })}
              selectedId={state.msg}
              onOpen={open}
              ctx={ctx}
              filters={state.filters}
              onColumnFilter={onColumnFilter}
              showFilterRow={prefs.showFilterRow}
              busy={q.isFetching && q.isPlaceholderData}
            />
            {rows.length === 0 && (
              <Empty icon={<Inbox size={28} />} title={t('table.empty')}>
                <p>{t('table.emptyHint')}</p>
                <Button icon={<RotateCcw size={14} />} onClick={() => setFilters(emptyFilters(prefs.defaultRange))}>
                  {t('filters.reset')}
                </Button>
              </Empty>
            )}
          </div>
        )}
        <Pager
          page={state.page}
          totalPages={q.data?.total_pages ?? 1}
          count={count}
          limit={limit}
          maxLimit={maxLimit}
          defaultLimit={defaultLimit}
          onPage={(page) => update({ page })}
          onRefresh={() => void q.refetch()}
          fetching={q.isFetching}
          updatedAt={q.dataUpdatedAt}
        />
      </div>

      <MessageDrawer id={state.msg} onClose={() => update({ msg: undefined })} onPrev={prev} onNext={next} state={state} />
    </div>
  );
}
