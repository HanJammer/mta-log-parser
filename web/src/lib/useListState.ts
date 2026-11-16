import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { parseSearch, toSearchParams, type Filters, type ListState } from './filters';
import { usePrefs } from './prefs';

/** List state (filters, page, sort, open message) mirrored in the URL query string. */
export function useListState() {
  const [search, setSearch] = useSearchParams();
  const { defaultRange } = usePrefs();
  const key = search.toString();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const state = useMemo(() => parseSearch(search, defaultRange), [key, defaultRange]);

  const update = useCallback(
    (patch: Partial<ListState> | ((s: ListState) => Partial<ListState>), opts: { push?: boolean } = {}) => {
      const current = parseSearch(new URLSearchParams(window.location.search), defaultRange);
      const delta = typeof patch === 'function' ? patch(current) : patch;
      const next = { ...current, ...delta };
      setSearch(toSearchParams(next, { defaultRange }), { replace: !opts.push });
    },
    [setSearch, defaultRange],
  );

  /** Replaces filters and goes back to page 1. */
  const setFilters = useCallback(
    (f: Filters | ((f: Filters) => Filters)) =>
      update((s) => ({ filters: typeof f === 'function' ? f(s.filters) : f, page: 1 })),
    [update],
  );

  return { state, update, setFilters };
}

/** Query string with only the filters (for links between Messages and Statistics). */
export function filtersOnlySearch(search: string, defaultRange: ListState['filters']['range']): string {
  const s = parseSearch(new URLSearchParams(search), defaultRange);
  const qs = toSearchParams({ filters: s.filters, page: 1, order: s.order, dir: s.dir }, { defaultRange }).toString();
  return qs ? `?${qs}` : '';
}
