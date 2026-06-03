import { useState, type FormEvent } from 'react';
import { Baby, LogIn, Hospital, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '@/lib/i18n';

export default function LoginPage() {
  const { login, error, loading } = useAuth();
  const t = useT();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(username, password);
    } catch {
      // error đã nằm trong context
    } finally {
      setSubmitting(false);
    }
  }

  const busy = submitting || loading;

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-blue-50 via-slate-50 to-emerald-50 p-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center">
            <Hospital className="text-white" size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-800">{t('brand.name')}</h1>
            <p className="text-xs text-slate-500">{t('brand.tagline')}</p>
          </div>
        </div>

        <h2 className="text-lg font-semibold text-slate-800 mb-1">{t('auth.login')}</h2>
        <p className="text-sm text-slate-500 mb-6">
          {t('auth.useInternalAccount')}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm font-medium text-slate-700 block mb-1" htmlFor="username">
              {t('auth.username')}
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-slate-700 block mb-1" htmlFor="password">
              {t('auth.password')}
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {error && (
            <div className="px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors shadow-md shadow-blue-200"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
            {busy ? t('auth.loggingIn') : t('auth.login')}
          </button>
        </form>

        <p className="text-[11px] text-slate-400 mt-6 text-center">
          {t('auth.backend')} · <code>http://127.0.0.1:8000</code>
        </p>
        <a
          href="/phu-huynh"
          className="mt-4 flex items-center justify-center gap-2 rounded-xl border border-sky-100 bg-sky-50 px-4 py-2.5 text-sm font-semibold text-sky-700 hover:bg-sky-100"
        >
          <Baby size={16} />
          {t('auth.parentPortal')}
        </a>
      </div>
    </div>
  );
}
