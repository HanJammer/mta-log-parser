import { useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertCircle, KeyRound, LogIn, UserPlus } from 'lucide-react';
import { api, ApiError } from '../../api/client';
import { keys, useSession } from '../../api/hooks';
import { LANGUAGES, setLang, type Lang } from '../../i18n';
import { BrandMark } from '../../shell/Brand';
import { Splash } from '../../shell/Splash';
import { errorText } from '../../lib/errors';
import { Button, Field, Input, Select } from '../../ui/primitives';
import { validateLogin, validatePassword } from './validation';

function AuthLayout({ children, title, domain }: { children: ReactNode; title: string; domain?: string }) {
  const { t, i18n } = useTranslation();
  return (
    <div className="auth">
      <div className="envelope">
        <div className="envelope-inner">
          <div className="auth-brand">
            <BrandMark size={34} />
            <div>
              <div className="auth-app">{t('app.title')}</div>
              {domain && <div className="auth-domain mono">{domain}</div>}
            </div>
          </div>
          <h1 className="auth-title">{title}</h1>
          {children}
          <div className="auth-lang">
            <Select value={i18n.language} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t('settings.language')}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>
    </div>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="form-error" role="alert">
      <AlertCircle size={15} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

/** Only same-app paths are accepted as a post-login target. */
function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//')) return '/';
  return next;
}

export function LoginPage() {
  const { t } = useTranslation();
  const session = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session.isPending) return <Splash />;
  if (session.data?.needs_setup) return <Navigate to="/setup" replace />;
  if (session.data?.authenticated) return <Navigate to={safeNext(params.get('next'))} replace />;
  const ldap = session.data?.auth_mode === 'ldap';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!login.trim() || !password) {
      setError(t('auth.fillBoth'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post('/login', { login: login.trim(), password });
      await qc.invalidateQueries({ queryKey: keys.session });
      navigate(safeNext(params.get('next')), { replace: true });
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={ldap ? t('auth.loginLdap') : t('auth.loginTitle')} domain={session.data?.config?.mail_domain}>
      <form className="auth-form" onSubmit={(e) => void submit(e)} noValidate>
        <Field label={t('auth.login')}>
          <Input autoFocus autoComplete="username" value={login} onChange={(e) => setLogin(e.target.value)} name="login" />
        </Field>
        <Field label={t('auth.password')}>
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} name="password" />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" icon={<LogIn size={16} />} disabled={busy} className="auth-submit">
          {t('auth.loginButton')}
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SetupPage() {
  const { t } = useTranslation();
  const session = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session.isPending) return <Splash />;
  if (!session.data?.needs_setup) return <Navigate to="/" replace />;

  const loginErr = validateLogin(login, t);
  const passErr = validatePassword(password, t);
  const confirmErr = confirm !== password ? t('accounts.mismatch') : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (loginErr || passErr || confirmErr) return;
    setBusy(true);
    setError(null);
    try {
      await api.post('/setup', { login, password });
      await qc.invalidateQueries({ queryKey: keys.session });
      navigate('/', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'ALREADY_SET_UP') {
        await qc.invalidateQueries({ queryKey: keys.session });
        navigate('/login', { replace: true });
      }
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title={t('auth.setupTitle')} domain={session.data?.config?.mail_domain}>
      <p className="auth-lead">{t('auth.setupLead')}</p>
      <form className="auth-form" onSubmit={(e) => void submit(e)} noValidate>
        <Field label={t('auth.login')} error={touched ? loginErr : null} hint={t('accounts.loginHint')}>
          <Input autoFocus autoComplete="username" value={login} onChange={(e) => setLogin(e.target.value)} />
        </Field>
        <Field label={t('auth.password')} error={touched ? passErr : null} hint={t('accounts.passwordHint')}>
          <Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} icon={<KeyRound size={14} />} />
        </Field>
        <Field label={t('accounts.confirm')} error={touched ? confirmErr : null}>
          <Input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" icon={<UserPlus size={16} />} disabled={busy} className="auth-submit">
          {t('auth.setupButton')}
        </Button>
      </form>
    </AuthLayout>
  );
}
