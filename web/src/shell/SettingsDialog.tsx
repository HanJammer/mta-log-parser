import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useSession } from '../api/hooks';
import { LANGUAGES, setLang, type Lang } from '../i18n';
import { DEFAULT_COLUMNS, resetPrefs, setPrefs, usePrefs, type Density, type ThemePref, type TimeZonePref } from '../lib/prefs';
import { RANGE_PRESETS, type RangePreset } from '../lib/filters';
import { tzLabel } from '../lib/format';
import { Button, Segmented, Select, Switch } from '../ui/primitives';
import { Dialog } from '../ui/overlays';

export const PAGE_SIZES = [25, 50, 100, 200, 500];
export const REFRESH_OPTIONS = [0, 30, 60, 300, 600, 1800];

export function refreshLabel(t: TFunction, sec: number) {
  if (!sec) return t('settings.refreshOff');
  return sec < 60 ? t('units.seconds', { count: sec }) : t('units.minutes', { count: sec / 60 });
}

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const prefs = usePrefs();
  const config = useSession().data?.config;
  const maxLimit = config?.max_limit ?? 1000;
  const sizes = PAGE_SIZES.filter((n) => n <= maxLimit);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('settings.title')}
      width={560}
      footer={
        <>
          <span className="muted-3 dialog-foot-note">{t('settings.storedLocally')}</span>
          <Button variant="ghost" onClick={() => resetPrefs()}>
            {t('settings.resetAll')}
          </Button>
          <Button variant="primary" onClick={onClose}>
            {t('common.done')}
          </Button>
        </>
      }
    >
      <div className="settings">
        <section>
          <h3>{t('settings.appearance')}</h3>
          <div className="settings-row">
            <span className="settings-label">{t('settings.language')}</span>
            <Select value={i18n.language} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t('settings.language')}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.theme')}</span>
            <Segmented<ThemePref>
              label={t('settings.theme')}
              value={prefs.theme}
              onChange={(theme) => setPrefs({ theme })}
              options={[
                { value: 'auto', label: <><Monitor size={14} aria-hidden="true" /> {t('settings.themeAuto')}</> },
                { value: 'light', label: <><Sun size={14} aria-hidden="true" /> {t('settings.themeLight')}</> },
                { value: 'dark', label: <><Moon size={14} aria-hidden="true" /> {t('settings.themeDark')}</> },
              ]}
            />
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.density')}</span>
            <Segmented<Density>
              label={t('settings.density')}
              value={prefs.density}
              onChange={(density) => setPrefs({ density })}
              options={[
                { value: 'compact', label: t('settings.densityCompact') },
                { value: 'comfortable', label: t('settings.densityComfortable') },
              ]}
            />
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.timeZone')}</span>
            <Segmented<TimeZonePref>
              label={t('settings.timeZone')}
              value={prefs.timeZone}
              onChange={(timeZone) => setPrefs({ timeZone })}
              options={[
                { value: 'local', label: `${t('settings.tzLocal')} (${tzLabel('local')})` },
                { value: 'utc', label: 'UTC' },
              ]}
            />
          </div>
          <div className="settings-row settings-row-switch">
            <Switch checked={prefs.coloredRows} onChange={(coloredRows) => setPrefs({ coloredRows })} label={t('settings.coloredRows')} hint={t('settings.coloredRowsHint')} />
          </div>
        </section>

        <section>
          <h3>{t('settings.messages')}</h3>
          <div className="settings-row">
            <span className="settings-label">{t('settings.pageSize')}</span>
            <Select value={prefs.pageSize} onChange={(e) => setPrefs({ pageSize: Number(e.target.value) })} aria-label={t('settings.pageSize')}>
              <option value={0}>{t('settings.serverDefault', { n: config?.default_limit ?? 50 })}</option>
              {sizes.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.defaultRange')}</span>
            <Select value={prefs.defaultRange} onChange={(e) => setPrefs({ defaultRange: e.target.value as RangePreset })} aria-label={t('settings.defaultRange')}>
              {RANGE_PRESETS.map((r) => (
                <option key={r} value={r}>
                  {t(`range.long.${r}`)}
                </option>
              ))}
            </Select>
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.refresh')}</span>
            <Select value={prefs.refresh} onChange={(e) => setPrefs({ refresh: Number(e.target.value) })} aria-label={t('settings.refresh')}>
              {REFRESH_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {refreshLabel(t, s)}
                </option>
              ))}
            </Select>
          </div>
          <div className="settings-row settings-row-switch">
            <Switch checked={prefs.showFilterRow} onChange={(showFilterRow) => setPrefs({ showFilterRow })} label={t('settings.filterRow')} hint={t('settings.filterRowHint')} />
          </div>
          <div className="settings-row settings-row-switch">
            <Switch checked={prefs.exportRecipients} onChange={(exportRecipients) => setPrefs({ exportRecipients })} label={t('settings.exportRecipients')} hint={t('settings.exportRecipientsHint')} />
          </div>
          <div className="settings-row">
            <span className="settings-label">{t('settings.layout')}</span>
            <Button size="sm" onClick={() => setPrefs({ columns: DEFAULT_COLUMNS, widths: {} })}>
              {t('settings.resetColumns')}
            </Button>
          </div>
        </section>
      </div>
    </Dialog>
  );
}
