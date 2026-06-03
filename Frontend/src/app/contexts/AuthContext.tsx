import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import * as api from '@/lib/api';

interface AuthContextValue {
  user: api.CurrentUser | null;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<api.CurrentUser | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(api.getToken()));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!api.getToken()) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    api
      .me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        api.logout();
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const doLogin = useCallback(async (username: string, password: string) => {
    setError(null);
    setLoading(true);
    try {
      await api.login(username, password);
      const u = await api.me();
      setUser(u);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const doLogout = useCallback(() => {
    api.logout();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    const u = await api.me();
    setUser(u);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, error, login: doLogin, logout: doLogout, refreshUser }),
    [user, loading, error, doLogin, doLogout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
