import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import ru from './locales/ru.json';
import pl from './locales/pl.json';

export const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'ru', name: 'Русский' },
  { code: 'pl', name: 'Polski' },
] as const;
export type Lang = (typeof LANGUAGES)[number]['code'];

const KEY = 'mlp.lang';

function isLang(v: unknown): v is Lang {
  return LANGUAGES.some((l) => l.code === v);
}

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (isLang(saved)) return saved;
  } catch {
    /* ignore */
  }
  for (const l of navigator.languages ?? [navigator.language]) {
    const base = l.toLowerCase().split('-')[0];
    if (isLang(base)) return base;
  }
  return 'en';
}

export function setLang(lang: Lang) {
  try {
    localStorage.setItem(KEY, lang);
  } catch {
    /* ignore */
  }
  void i18n.changeLanguage(lang);
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ru: { translation: ru }, pl: { translation: pl } },
  lng: initialLang(),
  fallbackLng: 'en',
  // React escapes text itself; translations never go into HTML sinks.
  interpolation: { escapeValue: false },
  returnNull: false,
});

const sync = (lng: string) => document.documentElement.setAttribute('lang', lng);
sync(i18n.language);
i18n.on('languageChanged', sync);

export default i18n;
