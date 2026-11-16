import { useTranslation } from 'react-i18next';
import { Button, Spinner } from '../ui/primitives';
import { BrandMark } from './Brand';

export function Splash({ error, onRetry }: { error?: Error | null; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="splash">
      <BrandMark size={40} />
      {error ? (
        <>
          <p className="splash-error">{t('errors.unreachable')}</p>
          <p className="muted-3 mono">{error.message}</p>
          {onRetry && <Button onClick={onRetry}>{t('common.retry')}</Button>}
        </>
      ) : (
        <Spinner size={20} label={t('common.loading')} />
      )}
    </div>
  );
}
