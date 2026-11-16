import { useEffect, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { onUnauthorized, PREFIX } from './api/client';
import { keys, useSession } from './api/hooks';
import type { Session } from './api/types';
import { AppShell } from './shell/AppShell';
import { LoginPage, SetupPage } from './pages/auth/AuthPages';
import { MessagesPage } from './pages/messages/MessagesPage';
import { StatsPage } from './pages/stats/StatsPage';
import { AccountsPage } from './pages/accounts/AccountsPage';
import { Toaster } from './ui/toast';
import { Splash } from './shell/Splash';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

/** On a 401 from any data call: mark the session as gone and go to the login screen. */
function UnauthorizedHandler() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    onUnauthorized(() => {
      qc.setQueryData<Session | undefined>(keys.session, (s) => (s ? { ...s, authenticated: false, login: null } : s));
      void qc.invalidateQueries({ queryKey: keys.session });
      if (!location.pathname.startsWith('/login')) {
        navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
      }
    });
    return () => onUnauthorized(null);
  }, [qc, navigate, location]);
  return null;
}

/** Sends the visitor to setup or login when the session requires it. */
function Protected({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.isPending) return <Splash />;
  if (session.isError) return <Splash error={session.error} onRetry={() => void session.refetch()} />;
  const s = session.data;
  if (s.needs_setup) return <Navigate to="/setup" replace />;
  if (!s.authenticated) {
    const next = location.pathname + location.search;
    return <Navigate to={next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}

function ToasterHost() {
  const { t } = useTranslation();
  return <Toaster closeLabel={t('common.close')} />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={PREFIX || '/'}>
        <UnauthorizedHandler />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route
            element={
              <Protected>
                <AppShell />
              </Protected>
            }
          >
            <Route index element={<MessagesPage />} />
            <Route path="stats" element={<StatsPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
        <ToasterHost />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
