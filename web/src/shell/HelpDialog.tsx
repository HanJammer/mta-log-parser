import { Trans, useTranslation } from 'react-i18next';
import type { Session } from '../api/types';
import { Dialog } from '../ui/overlays';

const TIPS = ['contains', 'click', 'combine', 'range', 'logs', 'drawer', 'share', 'export', 'top'] as const;

export function HelpDialog({ open, onClose, session }: { open: boolean; onClose: () => void; session: Session }) {
  const { t } = useTranslation();
  const c = session.config;
  const rows: Array<[string, string | number | undefined]> = [
    ['MTA', (c.mta || 'postfix').toUpperCase()],
    ['DEFAULT_LIMIT', c.default_limit],
    ['MAX_LIMIT', c.max_limit],
    ['HOUSEKEEPING_DAYS', c.housekeeping_days || undefined],
    ['DATETIME_FORMAT', c.datetime_format || undefined],
    ['EXCLUDE_FROM_TOP_SENDERS', c.exclude_from_top_senders?.join(', ') || undefined],
    ['EXCLUDE_FROM_TOP_RECIPIENTS', c.exclude_from_top_recipients?.join(', ') || undefined],
  ];
  return (
    <Dialog open={open} onClose={onClose} title={t('help.title')} width={640}>
      <ul className="tips">
        {TIPS.map((k) => (
          <li key={k}>
            <Trans i18nKey={`help.tips.${k}`} components={{ b: <strong />, code: <code />, kbd: <kbd /> }} />
          </li>
        ))}
      </ul>
      <h3 className="help-sub">{t('help.server')}</h3>
      <dl className="kv kv-tight">
        {rows
          .filter(([, v]) => v !== undefined && v !== '')
          .map(([k, v]) => (
            <div key={k} className="kv-row">
              <dt className="mono">{k}</dt>
              <dd className="mono">{String(v)}</dd>
            </div>
          ))}
        <div className="kv-row">
          <dt>{t('help.version')}</dt>
          <dd className="mono">{session.version}</dd>
        </div>
      </dl>
    </Dialog>
  );
}
