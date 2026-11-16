import { Ban, CircleCheck, CircleHelp, Clock3, Split, Undo2, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cx } from './primitives';

/** Each status has its own glyph shape so it reads without colour. */
export const STATUS_ICONS: Record<string, LucideIcon> = {
  sent: CircleCheck,
  deferred: Clock3,
  bounced: Undo2,
  reject: Ban,
  multiple: Split,
  unknown: CircleHelp,
};

export function statusKey(code: string | null | undefined): string {
  const c = (code || 'unknown').toLowerCase();
  return c in STATUS_ICONS ? c : 'unknown';
}

export function StatusIcon({ code, size = 14 }: { code: string; size?: number }) {
  const k = statusKey(code);
  const Icon = STATUS_ICONS[k];
  return <Icon size={size} strokeWidth={2.2} className={`st-icon st-${k}`} aria-hidden="true" />;
}

export function StatusBadge({ code, title, compact }: { code: string | null | undefined; title?: string; compact?: boolean }) {
  const { t } = useTranslation();
  const k = statusKey(code);
  const label = t(`status.${k}`, { defaultValue: code || k });
  return (
    <span className={cx('badge', `st-${k}`, compact && 'badge-compact')} title={title ?? label}>
      <StatusIcon code={k} size={compact ? 13 : 14} />
      <span>{label}</span>
    </span>
  );
}
