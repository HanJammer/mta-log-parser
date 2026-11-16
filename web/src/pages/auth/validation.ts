import type { TFunction as T } from 'i18next';

/** Login: min 3 chars, `[A-Za-z0-9._@-]` (DESIGN-v2.md, "Session and accounts"). */
export function validateLogin(login: string, t: T): string | null {
  if (!login) return t('accounts.loginRequired');
  if (login.length < 3) return t('accounts.loginShort', { n: 3 });
  if (!/^[A-Za-z0-9._@-]+$/.test(login)) return t('accounts.loginChars');
  return null;
}

export function validatePassword(password: string, t: T): string | null {
  if (!password) return t('accounts.passwordRequired');
  if (password.length < 8) return t('accounts.passwordShort', { n: 8 });
  return null;
}
