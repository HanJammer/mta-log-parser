import { useEffect, useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { KeyRound, Plus, Trash2, UserRound } from 'lucide-react';
import { ApiError } from '../../api/client';
import { useSession, useUserMutations, useUsers } from '../../api/hooks';
import { Button, Empty, Field, Input, Spinner } from '../../ui/primitives';
import { Dialog } from '../../ui/overlays';
import { toast } from '../../ui/toast';
import { validateLogin, validatePassword } from '../auth/validation';

type Mode = { kind: 'create' } | { kind: 'password'; login: string } | { kind: 'delete'; login: string } | null;

function errText(err: unknown, t: (k: string) => string, on409?: string): string {
  if (err instanceof ApiError) {
    if (err.status === 409 && on409) {
      const base = t(on409);
      return err.message && err.message.toLowerCase() !== base.toLowerCase() ? `${base} (${err.message})` : base;
    }
    return err.message || err.code;
  }
  return err instanceof Error ? err.message : String(err);
}

export function AccountsPage() {
  const { t } = useTranslation();
  const session = useSession().data;
  const ldap = session?.auth_mode === 'ldap';
  const users = useUsers(!ldap);
  const [mode, setMode] = useState<Mode>(null);

  useEffect(() => {
    document.title = `${t('nav.accounts')} · ${t('app.title')}`;
  }, [t]);

  if (ldap) return <Navigate to="/" replace />;

  return (
    <div className="page-accounts">
      <div className="page-head">
        <div>
          <h1>{t('accounts.title')}</h1>
          <p className="muted-2">{t('accounts.lead')}</p>
        </div>
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setMode({ kind: 'create' })}>
          {t('accounts.create')}
        </Button>
      </div>
      <div className="panel">
        {users.isPending ? (
          <div className="panel-loading">
            <Spinner size={18} label={t('common.loading')} />
          </div>
        ) : users.isError ? (
          <Empty title={t('errors.loadFailed')}>{users.error.message}</Empty>
        ) : users.data.length === 0 ? (
          <Empty title={t('accounts.none')} />
        ) : (
          <ul className="userlist">
            {users.data.map((u) => (
              <li key={u.login} className="userrow">
                <UserRound size={16} aria-hidden="true" className="muted-3" />
                <span className="userrow-login">{u.login}</span>
                {u.login === session?.login && <span className="tag">{t('accounts.you')}</span>}
                <span className="userrow-actions">
                  <Button size="sm" icon={<KeyRound size={14} />} onClick={() => setMode({ kind: 'password', login: u.login })}>
                    {t('accounts.changePassword')}
                  </Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={() => setMode({ kind: 'delete', login: u.login })} aria-label={`${t('accounts.delete')}: ${u.login}`} title={t('accounts.delete')} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {mode?.kind === 'create' && <CreateDialog onClose={() => setMode(null)} />}
      {mode?.kind === 'password' && <PasswordDialog login={mode.login} onClose={() => setMode(null)} />}
      {mode?.kind === 'delete' && <DeleteDialog login={mode.login} onClose={() => setMode(null)} />}
    </div>
  );
}

function CreateDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { create } = useUserMutations();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState(false);
  const loginErr = validateLogin(login, t);
  const passErr = validatePassword(password, t);
  const confirmErr = confirm !== password ? t('accounts.mismatch') : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (loginErr || passErr || confirmErr) return;
    create.mutate(
      { login, password },
      {
        onSuccess: () => {
          toast('success', t('accounts.created', { login }));
          onClose();
        },
      },
    );
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('accounts.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="create-user" disabled={create.isPending}>
            {t('accounts.create')}
          </Button>
        </>
      }
    >
      <form id="create-user" className="form-stack" onSubmit={submit} noValidate>
        <Field label={t('auth.login')} error={touched ? loginErr : null} hint={t('accounts.loginHint')}>
          <Input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="off" data-autofocus />
        </Field>
        <Field label={t('auth.password')} error={touched ? passErr : null} hint={t('accounts.passwordHint')}>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label={t('accounts.confirm')} error={touched ? confirmErr : null}>
          <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </Field>
        {create.isError && <p className="error-text">{errText(create.error, t, 'accounts.exists')}</p>}
      </form>
    </Dialog>
  );
}

function PasswordDialog({ login, onClose }: { login: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { setPassword } = useUserMutations();
  const [password, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState(false);
  const passErr = validatePassword(password, t);
  const confirmErr = confirm !== password ? t('accounts.mismatch') : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (passErr || confirmErr) return;
    setPassword.mutate(
      { login, password },
      {
        onSuccess: () => {
          toast('success', t('accounts.passwordChanged', { login }));
          onClose();
        },
      },
    );
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('accounts.changePasswordFor', { login })}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="set-password" disabled={setPassword.isPending}>
            {t('accounts.savePassword')}
          </Button>
        </>
      }
    >
      <form id="set-password" className="form-stack" onSubmit={submit} noValidate>
        <Field label={t('accounts.newPassword')} error={touched ? passErr : null} hint={t('accounts.passwordHint')}>
          <Input type="password" value={password} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" data-autofocus />
        </Field>
        <Field label={t('accounts.confirm')} error={touched ? confirmErr : null}>
          <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </Field>
        {setPassword.isError && <p className="error-text">{errText(setPassword.error, t)}</p>}
      </form>
    </Dialog>
  );
}

function DeleteDialog({ login, onClose }: { login: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { remove } = useUserMutations();
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('accounts.deleteTitle', { login })}
      footer={
        <>
          <Button onClick={onClose} data-autofocus>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            icon={<Trash2 size={14} />}
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(login, {
                onSuccess: () => {
                  toast('success', t('accounts.deleted', { login }));
                  onClose();
                },
              })
            }
          >
            {t('accounts.delete')}
          </Button>
        </>
      }
    >
      <p>{t('accounts.deleteBody', { login })}</p>
      {remove.isError && <p className="error-text">{errText(remove.error, t, 'accounts.lastAccount')}</p>}
    </Dialog>
  );
}
