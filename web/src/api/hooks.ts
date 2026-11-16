import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Query } from './client';
import type {
  Email,
  EmailList,
  Facets,
  HostStats,
  Session,
  TimelinePoint,
  TopRecipient,
  TopRelay,
  TopSender,
  User,
} from './types';
import { toApiFilterQuery, type Filters, type ListState } from '../lib/filters';

export const keys = {
  session: ['session'] as const,
  emails: (s: unknown) => ['emails', s] as const,
  email: (id: string) => ['email', id] as const,
  facets: ['facets'] as const,
  processing: ['process_check'] as const,
  users: ['users'] as const,
  stats: (kind: string, f: unknown) => ['stats', kind, f] as const,
};

export function useSession() {
  return useQuery({
    queryKey: keys.session,
    queryFn: () => api.get<Session>('/session'),
    staleTime: 60_000,
    retry: 1,
  });
}

export const encodeId = (id: string) => encodeURIComponent(id);

/** Builds the full list query: filters (relative range resolved now), paging and sort. */
export function emailsQuery(state: ListState, limit: number, now = Date.now()): Query {
  return {
    ...toApiFilterQuery(state.filters, now),
    page: state.page,
    limit,
    order: state.order,
    order_dir: state.dir,
  };
}

export function useEmails(state: ListState, limit: number, refreshSec: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.emails({ f: state.filters, page: state.page, order: state.order, dir: state.dir, limit }),
    // No AbortSignal: cancelling an in-flight request makes the server drop the query mid-way,
    // which can break its shared RethinkDB connection for concurrent requests.
    queryFn: () => api.get<EmailList>('/emails', emailsQuery(state, limit)),
    placeholderData: keepPreviousData,
    refetchInterval: refreshSec > 0 ? refreshSec * 1000 : false,
    enabled,
    retry: false,
  });
}

export function useEmail(id: string | undefined) {
  return useQuery({
    queryKey: keys.email(id ?? ''),
    queryFn: () => api.get<Email>(`/emails/${encodeId(id!)}`),
    enabled: !!id,
    retry: false,
  });
}

export function useFacets() {
  return useQuery({ queryKey: keys.facets, queryFn: () => api.get<Facets>('/facets'), staleTime: 5 * 60_000 });
}

export function useProcessing(enabled: boolean) {
  return useQuery({
    queryKey: keys.processing,
    queryFn: () => api.get<{ processing: boolean }>('/process_check'),
    refetchInterval: (q) => (q.state.data?.processing ? 3000 : 15000),
    enabled,
    retry: false,
  });
}

function useStat<T>(kind: string, filters: Filters, extra: Query, enabled = true) {
  return useQuery({
    queryKey: keys.stats(kind, { filters, extra }),
    queryFn: () => api.get<T>('/stats', { ...toApiFilterQuery(filters), ...extra }),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    enabled,
    retry: false,
  });
}

export const useTopSenders = (f: Filters) => useStat<TopSender[]>('top_senders', f, { top_senders: 1 });
export const useTopRecipients = (f: Filters) => useStat<TopRecipient[]>('top_recipients', f, { top_recipients: 1 });
export const useTopRelays = (f: Filters) => useStat<TopRelay[]>('top_relays', f, { top_relays: 1 });
export const useByHost = (f: Filters) => useStat<HostStats[]>('by_host', f, { by_host: 1 });
/** `tz` (`+02:00`) puts bucket boundaries on local hours/days. */
export const useTimeline = (f: Filters, bucket: 'hour' | 'day', tz: string) =>
  useStat<TimelinePoint[]>(`timeline_${bucket}_${tz}`, f, { timeline: 1, bucket, tz });

/** Overall counter for one status code (not filtered). */
export function useStatusCount(code: string) {
  return useQuery({
    queryKey: ['stats', 'statuses', code],
    queryFn: () => api.get<Record<string, number>>('/stats', { statuses: code }),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useUsers(enabled: boolean) {
  return useQuery({ queryKey: keys.users, queryFn: () => api.get<User[]>('/users'), enabled });
}

export function useUserMutations() {
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: keys.users });
  return {
    create: useMutation({ mutationFn: (b: { login: string; password: string }) => api.post('/users', b), onSuccess: done }),
    setPassword: useMutation({
      mutationFn: (b: { login: string; password: string }) => api.put(`/users/${encodeURIComponent(b.login)}`, { password: b.password }),
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: (login: string) => api.del(`/users/${encodeURIComponent(login)}`), onSuccess: done }),
  };
}
