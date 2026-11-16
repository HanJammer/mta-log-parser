/**
 * Thin fetch wrapper for the MLP JSON API.
 * - base URL = PATH_PREFIX (from <meta name="mlp-prefix">) + /api
 * - state-changing requests send JSON and `X-Requested-With: mlp` (CSRF guard)
 * - a 401 outside the session/login endpoints notifies the app, which goes to the login screen
 */

function readPrefix(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="mlp-prefix"]');
  let value = (meta?.content ?? '').trim();
  // unreplaced placeholder (Vite dev server, or index.html opened without the backend)
  if (/^__[A-Z_]+__$/.test(value)) value = '';
  return value.replace(/\/+$/, '');
}

/** PATH_PREFIX without trailing slash ('' when served at the root). */
export const PREFIX = readPrefix();
export const API_BASE = `${PREFIX}/api`;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export type Query = Record<string, string | number | undefined | null>;

export function toSearch(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

let unauthorizedListener: (() => void) | null = null;
export function onUnauthorized(listener: (() => void) | null): void {
  unauthorizedListener = listener;
}

const AUTH_PATHS = ['/session', '/login', '/logout', '/setup'];

type MockHandler = (method: string, path: string, query: Query | undefined, body: unknown) => Promise<Response>;
let mock: MockHandler | null = null;
let mockReady: Promise<void> | null = null;
if (import.meta.env.VITE_MOCK === '1') {
  mockReady = import('./mock/handler').then((m) => {
    mock = m.handle;
  });
}

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const { query, body, signal } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    headers['X-Requested-With'] = 'mlp';
  }

  let response: Response;
  try {
    if (mockReady) await mockReady;
    response = mock
      ? await mock(method, path, query, body)
      : await fetch(API_BASE + path + toSearch(query), {
          method,
          headers,
          body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
          credentials: 'same-origin',
          signal,
        });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, 'NETWORK', err instanceof Error ? err.message : String(err));
  }

  if (response.status === 204) return undefined as T;
  const isJson = (response.headers.get('Content-Type') ?? '').includes('json');
  const payload: unknown = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const p = (payload ?? {}) as { error_code?: string; message?: string };
    const err = new ApiError(
      response.status,
      p.error_code ?? (response.status === 401 ? 'UNAUTHORIZED' : `HTTP_${response.status}`),
      p.message ?? response.statusText,
    );
    if (response.status === 401 && !AUTH_PATHS.includes(path)) unauthorizedListener?.();
    throw err;
  }
  if (!isJson) throw new ApiError(response.status, 'BAD_RESPONSE', 'Unexpected response type');
  // Some list answers keep the legacy `{error: true}` envelope with HTTP 200.
  const env = payload as { error?: unknown; error_code?: string; message?: string } | null;
  if (env && typeof env === 'object' && !Array.isArray(env) && env.error === true) {
    throw new ApiError(response.status, env.error_code ?? 'API_ERROR', env.message ?? 'API error');
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
  del: <T>(path: string) => request<T>('DELETE', path),
};
