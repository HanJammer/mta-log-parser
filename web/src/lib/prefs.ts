/** Per-browser user preferences, kept in localStorage. */
import { useSyncExternalStore } from 'react';
import type { RangePreset } from './filters';

export type ThemePref = 'auto' | 'light' | 'dark';
export type Density = 'compact' | 'comfortable';
export type TimeZonePref = 'local' | 'utc';

export interface Prefs {
  theme: ThemePref;
  /** 0 = server DEFAULT_LIMIT */
  pageSize: number;
  density: Density;
  /** seconds, 0 = off */
  refresh: number;
  coloredRows: boolean;
  timeZone: TimeZonePref;
  defaultRange: RangePreset;
  /** visible columns, in display order */
  columns: string[];
  widths: Record<string, number>;
  showFilterRow: boolean;
  hiddenTop: { senders: string[]; recipients: string[]; relays: string[] };
  exportRecipients: boolean;
}

export const DEFAULT_COLUMNS = ['time', 'host', 'from', 'to', 'subject', 'status', 'relay', 'client'];

export const DEFAULT_PREFS: Prefs = {
  theme: 'auto',
  pageSize: 0,
  density: 'compact',
  refresh: 0,
  coloredRows: false,
  timeZone: 'local',
  defaultRange: '24h',
  columns: DEFAULT_COLUMNS,
  widths: {},
  showFilterRow: false,
  hiddenTop: { senders: [], recipients: [], relays: [] },
  exportRecipients: true,
};

const KEY = 'mlp.prefs';
const THEME_KEY = 'mlp.theme';
const listeners = new Set<() => void>();
const media = window.matchMedia('(prefers-color-scheme: dark)');

function load(): Prefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<Prefs>;
    return {
      ...DEFAULT_PREFS,
      ...parsed,
      hiddenTop: { ...DEFAULT_PREFS.hiddenTop, ...(parsed.hiddenTop ?? {}) },
      columns: Array.isArray(parsed.columns) && parsed.columns.length ? parsed.columns : DEFAULT_COLUMNS,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

let prefs: Prefs = load();

function applyTheme(): void {
  const dark = prefs.theme === 'dark' || (prefs.theme === 'auto' && media.matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-density', prefs.density);
}
media.addEventListener('change', applyTheme);
applyTheme();

export function getPrefs(): Prefs {
  return prefs;
}

export function setPrefs(patch: Partial<Prefs> | ((p: Prefs) => Partial<Prefs>)): void {
  const delta = typeof patch === 'function' ? patch(prefs) : patch;
  prefs = { ...prefs, ...delta };
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
    if (prefs.theme === 'auto') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, prefs.theme);
  } catch {
    /* storage unavailable: keep for this tab only */
  }
  applyTheme();
  listeners.forEach((l) => l());
}

export function resetPrefs(keep: Array<keyof Prefs> = []): void {
  const kept: Partial<Prefs> = {};
  for (const k of keep) (kept as Record<string, unknown>)[k] = prefs[k];
  setPrefs({ ...DEFAULT_PREFS, ...kept });
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, getPrefs);
}

/** Effective dark/light state (for charts that need concrete colours). */
export function useIsDark(): boolean {
  usePrefs();
  return useSyncExternalStore(
    (cb) => {
      media.addEventListener('change', cb);
      return () => media.removeEventListener('change', cb);
    },
    () => document.documentElement.getAttribute('data-theme') === 'dark',
  );
}
