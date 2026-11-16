import { useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { BarChart3, CircleHelp, Inbox, LogOut, Settings2, ShieldCheck, UserRound, Users } from 'lucide-react';
import { api } from '../api/client';
import { keys, useProcessing, useSession } from '../api/hooks';
import type { Session } from '../api/types';
import { filtersOnlySearch } from '../lib/useListState';
import { usePrefs } from '../lib/prefs';
import { Button, Spinner } from '../ui/primitives';
import { Popover } from '../ui/overlays';
import { toast } from '../ui/toast';
import { BrandMark } from './Brand';
import { Footer } from './Footer';
import { SettingsDialog } from './SettingsDialog';
import { HelpDialog } from './HelpDialog';

export function AppShell() {
  const { t } = useTranslation();
  const session = useSession().data as Session;
  const processing = useProcessing(true).data?.processing ?? false;
  const location = useLocation();
  const { defaultRange } = usePrefs();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const linkSearch = filtersOnlySearch(location.search, defaultRange);
  const ldap = session.auth_mode === 'ldap';

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-stripe" aria-hidden="true" />
        <div className="topbar-row">
          <NavLink to={{ pathname: '/', search: linkSearch }} className="brand" aria-label={t('app.title')}>
            <BrandMark />
            <span className="brand-name">{t('app.title')}</span>
            {session.config.mail_domain && <span className="brand-domain mono">{session.config.mail_domain}</span>}
          </NavLink>
          <nav className="nav" aria-label={t('nav.label')}>
            <NavLink to={{ pathname: '/', search: linkSearch }} end className="nav-link">
              <Inbox size={15} aria-hidden="true" />
              <span>{t('nav.messages')}</span>
            </NavLink>
            <NavLink to={{ pathname: '/stats', search: linkSearch }} className="nav-link">
              <BarChart3 size={15} aria-hidden="true" />
              <span>{t('nav.stats')}</span>
            </NavLink>
            {ldap ? (
              <span className="nav-link is-disabled" title={t('nav.ldapTitle')}>
                <ShieldCheck size={15} aria-hidden="true" />
                <span>LDAP</span>
              </span>
            ) : (
              <NavLink to="/accounts" className="nav-link">
                <Users size={15} aria-hidden="true" />
                <span>{t('nav.accounts')}</span>
              </NavLink>
            )}
          </nav>
          <div className="topbar-tools">
            {processing && (
              <span className="parsing-pill" title={t('processing.banner')}>
                <Spinner size={11} />
                <span>{t('processing.short')}</span>
              </span>
            )}
            <Button variant="ghost" icon={<CircleHelp size={17} />} onClick={() => setHelpOpen(true)} aria-label={t('help.title')} title={t('help.title')} />
            <Button variant="ghost" icon={<Settings2 size={17} />} onClick={() => setSettingsOpen(true)} aria-label={t('settings.title')} title={t('settings.title')} />
            <UserMenu login={session.login ?? ''} />
          </div>
        </div>
      </header>
      {processing && (
        <div className="banner banner-info" role="status">
          <Spinner size={13} />
          <span>{t('processing.banner')}</span>
        </div>
      )}
      <main className="main">
        <Outlet />
      </main>
      <Footer version={session.version} />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} session={session} />
    </div>
  );
}

function UserMenu({ login }: { login: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = async () => {
    setOpen(false);
    try {
      await api.post('/logout');
    } catch {
      /* the session is gone either way */
    }
    qc.clear();
    await qc.invalidateQueries({ queryKey: keys.session });
    toast('success', t('auth.loggedOut'));
    navigate('/login', { replace: true });
  };
  return (
    <>
      <Button ref={anchor} variant="ghost" icon={<UserRound size={16} />} onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} className="user-btn">
        <span className="user-login">{login}</span>
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} align="end" label={t('auth.userMenu')}>
        <div className="menu">
          <div className="menu-note">
            {t('auth.signedInAs')} <strong>{login}</strong>
          </div>
          <button type="button" className="menu-item" onClick={() => void logout()} data-autofocus>
            <LogOut size={15} aria-hidden="true" />
            {t('auth.logout')}
          </button>
        </div>
      </Popover>
    </>
  );
}
