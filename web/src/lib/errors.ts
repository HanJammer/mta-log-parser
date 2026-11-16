import type { TFunction } from 'i18next';
import { ApiError } from '../api/client';

/** Error codes of the backend that have their own localized text (`errors.code.<CODE>`). */
const KNOWN = new Set([
  'NETWORK',
  'UNAUTHORIZED',
  'INVALID_CREDENTIALS',
  'TOO_MANY_ATTEMPTS',
  'CSRF_FAILED',
  'INVALID_FILTER',
  'INVALID_DATE',
  'INVALID_ORDER',
  'INVALID_PARAMETER',
  'INVALID_ACCOUNT',
  'LOCAL_AUTH_ONLY',
  'RESULT_TOO_LARGE',
  'TIME_WINDOW_REQUIRED',
  'NOT_FOUND',
  'USER_EXISTS',
  'ALREADY_SET_UP',
  'LAST_ACCOUNT',
  'QUERY_TIMEOUT',
  'DB_UNAVAILABLE',
]);

/** Codes whose server message names the offending field or rule, so it is worth showing. */
const WITH_DETAIL = new Set(['INVALID_FILTER', 'INVALID_DATE', 'INVALID_PARAMETER', 'INVALID_ACCOUNT', 'INVALID_ORDER']);

/**
 * Human-readable text for an API error in the current language. Validation errors
 * (`INVALID_FILTER`, `INVALID_ACCOUNT`, …) append the server's message because it names the
 * offending field or rule.
 */
export function errorText(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.code === 'TOO_MANY_ATTEMPTS') {
      return err.retryAfter ? t('errors.code.TOO_MANY_ATTEMPTS_WAIT', { n: Math.ceil(err.retryAfter / 60) }) : t('errors.code.TOO_MANY_ATTEMPTS');
    }
    if (KNOWN.has(err.code)) {
      const base = t(`errors.code.${err.code}`);
      const detail = WITH_DETAIL.has(err.code) && err.message ? ` ${err.message}` : '';
      return base + detail;
    }
    return err.message || err.code;
  }
  return err instanceof Error ? err.message : String(err);
}
