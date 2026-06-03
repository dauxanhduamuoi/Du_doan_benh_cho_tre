import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  User as UserIcon,
  ShieldCheck,
  KeyRound,
  LogOut,
  BadgeCheck,
  AlertTriangle,
  Copy,
  CheckCircle2,
  Loader2,
  Monitor,
  RefreshCcw,
  Save,
  XCircle,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import * as api from '@/lib/api';
import { getToken } from '@/lib/api';
import { useT } from '@/lib/i18n';

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function maskToken(token: string | null, noToken: string): string {
  if (!token) return noToken;
  if (token.length <= 16) return token;
  return `${token.slice(0, 12)}…${token.slice(-6)}`;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso ?? '—';
  }
}

function summarizeUserAgent(ua: string | null): string {
  if (!ua) return 'Unknown device';
  if (/Edg\//.test(ua)) return 'Microsoft Edge';
  if (/Chrome\//.test(ua)) return 'Chrome';
  if (/Firefox\//.test(ua)) return 'Firefox';
  if (/Safari\//.test(ua)) return 'Safari';
  return ua.slice(0, 64);
}

export default function Account() {
  const { user, logout, refreshUser } = useAuth();
  const t = useT();
  const token = useMemo(() => getToken(), []);
  const [copied, setCopied] = useState(false);
  const [profileFullName, setProfileFullName] = useState('');
  const [profileBirthDate, setProfileBirthDate] = useState('');
  const [profileGender, setProfileGender] = useState('');
  const [profilePosition, setProfilePosition] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);

  // Đổi mật khẩu
  const [pwdCurrent, setPwdCurrent] = useState('');
  const [pwdNew, setPwdNew] = useState('');
  const [pwdConfirm, setPwdConfirm] = useState('');
  const [pwdSaving, setPwdSaving] = useState(false);
  const [pwdSuccess, setPwdSuccess] = useState(false);
  const [pwdError, setPwdError] = useState<string | null>(null);

  // Sessions
  const [sessions, setSessions] = useState<api.LoginSessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError(null);
    try {
      const rows = await api.listSessions();
      setSessions(rows);
    } catch (e) {
      setSessionsError(e instanceof Error ? e.message : String(e));
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadSessions();
  }, [loadSessions, user]);

  useEffect(() => {
    if (!user) return;
    setProfileFullName(user.full_name ?? '');
    setProfileBirthDate(user.birth_date ?? '');
    setProfileGender(user.gender ?? '');
    setProfilePosition(user.position ?? '');
  }, [user]);

  if (!user) {
    return (
      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm text-sm text-slate-500">
        {t('account.noSession')}
      </div>
    );
  }

  const displayName = user.full_name || user.username;
  const roleLabel = user.role === 'admin' ? t('user.adminRole') : t('user.staffRole');

  async function copyToken() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }

  async function handleChangePassword() {
    setPwdError(null);
    setPwdSuccess(false);
    if (!pwdCurrent || !pwdNew) {
      setPwdError(t('account.security.changePwd.required'));
      return;
    }
    if (pwdNew.length < 6) {
      setPwdError(t('account.security.changePwd.tooShort'));
      return;
    }
    if (pwdNew !== pwdConfirm) {
      setPwdError(t('account.security.changePwd.mismatch'));
      return;
    }
    setPwdSaving(true);
    try {
      await api.changePassword(pwdCurrent, pwdNew);
      setPwdCurrent('');
      setPwdNew('');
      setPwdConfirm('');
      setPwdSuccess(true);
      setTimeout(() => setPwdSuccess(false), 3000);
    } catch (e) {
      setPwdError(e instanceof Error ? e.message : String(e));
    } finally {
      setPwdSaving(false);
    }
  }

  async function handleSaveProfile() {
    setProfileSaving(true);
    setProfileMessage(null);
    try {
      await api.updateProfile({
        full_name: profileFullName,
        birth_date: profileBirthDate,
        gender: profileGender,
        position: profilePosition,
      });
      await refreshUser();
      setProfileMessage('Đã cập nhật thông tin cá nhân.');
    } catch (e) {
      setProfileMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleRevoke(id: number) {
    try {
      await api.revokeSession(id);
      await loadSessions();
    } catch (e) {
      setSessionsError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRevokeOthers() {
    try {
      await api.revokeOtherSessions();
      await loadSessions();
    } catch (e) {
      setSessionsError(e instanceof Error ? e.message : String(e));
    }
  }

  const activeSessions = sessions.filter((s) => !s.revoked_at);
  const revokedSessions = sessions.filter((s) => s.revoked_at);
  const confirmLogout = () => {
    if (window.confirm('Bạn có chắc chắn muốn đăng xuất không?')) {
      logout();
    }
  };

  return (
    <div className="space-y-6">
      {/* Profile card */}
      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="flex items-center gap-5">
          <div className="w-20 h-20 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center ring-4 ring-blue-100 shrink-0">
            <span className="text-white font-bold text-2xl">{initialsOf(displayName)}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-semibold text-slate-800 truncate">{displayName}</h2>
              {user.is_active ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <BadgeCheck size={12} />
                  {t('common.active')}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-50 text-red-700 border border-red-200">
                  <AlertTriangle size={12} />
                  {t('common.inactive')}
                </span>
              )}
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${
                  user.role === 'admin'
                    ? 'bg-purple-50 text-purple-700 border border-purple-200'
                    : 'bg-slate-100 text-slate-600 border border-slate-200'
                }`}
              >
                <ShieldCheck size={12} />
                {roleLabel}
              </span>
            </div>
            <p className="text-sm text-slate-500 mt-1">@{user.username} · ID #{user.id}</p>
          </div>
          <button
            onClick={confirmLogout}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors shrink-0"
          >
            <LogOut size={16} />
            {t('user.logout')}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Section icon={UserIcon} title={t('account.profile.title')}>
          <InfoRow label={t('account.profile.username')} value={user.username} />
          <EditableInput label="Họ và tên" value={profileFullName} onChange={setProfileFullName} />
          <EditableInput label="Ngày sinh" type="date" value={profileBirthDate} onChange={setProfileBirthDate} />
          <EditableInput label="Giới tính" value={profileGender} onChange={setProfileGender} placeholder="Nam, nữ, khác..." />
          <EditableInput label="Chức vụ" value={profilePosition} onChange={setProfilePosition} placeholder="Bác sĩ, điều dưỡng, y tá, nhân viên..." />
          <InfoRow label={t('account.profile.role')} value={roleLabel} />
          <InfoRow
            label={t('account.profile.status')}
            value={user.is_active ? t('common.active') : t('common.inactive')}
          />
          <InfoRow label={t('account.profile.id')} value={`#${user.id}`} />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={handleSaveProfile}
              disabled={profileSaving}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
            >
              {profileSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Lưu thông tin
            </button>
            {profileMessage && <span className="text-xs text-slate-500">{profileMessage}</span>}
          </div>
        </Section>

        <Section icon={ShieldCheck} title={t('account.session.title')}>
          <p className="text-sm text-slate-600">{t('account.session.desc')}</p>
          <div className="mt-3 p-3 rounded-lg bg-slate-50 border border-slate-200">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <KeyRound size={12} /> {t('account.session.accessToken')}
            </div>
            <div className="font-mono text-xs break-all text-slate-700">
              {maskToken(token, t('account.noToken'))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={copyToken}
                disabled={!token}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-white border border-slate-200 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-40"
              >
                {copied ? <CheckCircle2 size={12} className="text-emerald-600" /> : <Copy size={12} />}
                {copied ? t('account.session.copied') : t('account.session.copy')}
              </button>
              <span className="text-[11px] text-slate-400">{t('account.session.warn')}</span>
            </div>
          </div>
        </Section>
      </div>

      {/* Đổi mật khẩu */}
      <Section icon={KeyRound} title={t('account.security.changePwd.title')}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <PasswordInput
            label={t('account.security.changePwd.current')}
            value={pwdCurrent}
            onChange={setPwdCurrent}
          />
          <PasswordInput
            label={t('account.security.changePwd.new')}
            value={pwdNew}
            onChange={setPwdNew}
            hint={t('account.security.changePwd.hint')}
          />
          <PasswordInput
            label={t('account.security.changePwd.confirm')}
            value={pwdConfirm}
            onChange={setPwdConfirm}
          />
        </div>
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <button
            onClick={handleChangePassword}
            disabled={pwdSaving}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
          >
            {pwdSaving ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
            {t('account.security.changePwd.submit')}
          </button>
          {pwdSuccess && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-1 rounded">
              <CheckCircle2 size={12} /> {t('account.security.changePwd.success')}
            </span>
          )}
          {pwdError && (
            <span className="inline-flex items-center gap-1 text-xs text-red-700 bg-red-50 border border-red-200 px-2 py-1 rounded">
              <AlertTriangle size={12} /> {pwdError}
            </span>
          )}
        </div>
      </Section>

      {/* Phiên đăng nhập */}
      <Section icon={Monitor} title={t('account.sessions.title')}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm text-slate-500">{t('account.sessions.desc')}</p>
          <div className="flex items-center gap-2">
            <button
              onClick={loadSessions}
              disabled={sessionsLoading}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded hover:bg-slate-50 disabled:opacity-60"
            >
              {sessionsLoading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RefreshCcw size={12} />
              )}
              {t('common.refresh')}
            </button>
            {activeSessions.length > 1 && (
              <button
                onClick={handleRevokeOthers}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-xs text-red-700 bg-red-50 border border-red-200 rounded hover:bg-red-100"
              >
                <LogOut size={12} /> {t('account.sessions.revokeOthers')}
              </button>
            )}
          </div>
        </div>

        {sessionsError && (
          <div className="mb-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            {sessionsError}
          </div>
        )}

        {sessions.length === 0 && !sessionsLoading && (
          <p className="text-sm text-slate-500">{t('common.noData')}</p>
        )}

        <div className="space-y-2">
          {[...activeSessions, ...revokedSessions].map((s) => (
            <div
              key={s.id}
              className={`flex items-start justify-between gap-3 px-3 py-2.5 rounded-lg border ${
                s.is_current
                  ? 'border-blue-200 bg-blue-50'
                  : s.revoked_at
                    ? 'border-slate-200 bg-slate-50 opacity-70'
                    : 'border-slate-200 bg-white'
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-slate-800">
                    {summarizeUserAgent(s.user_agent)}
                  </span>
                  {s.is_current && (
                    <span className="text-[10px] font-medium text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded">
                      {t('account.sessions.current')}
                    </span>
                  )}
                  {s.revoked_at && (
                    <span className="text-[10px] font-medium text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                      {t('account.sessions.revoked')}
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-1 grid grid-cols-1 md:grid-cols-3 gap-1">
                  <span>IP: {s.ip_address || '—'}</span>
                  <span>{t('account.sessions.startedAt')}: {formatDateTime(s.created_at)}</span>
                  <span>{t('account.sessions.lastSeen')}: {formatDateTime(s.last_seen_at)}</span>
                </div>
              </div>
              {!s.is_current && !s.revoked_at && (
                <button
                  onClick={() => handleRevoke(s.id)}
                  className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-700 hover:bg-red-50 rounded"
                  title={t('account.sessions.revoke')}
                >
                  <XCircle size={14} />
                  {t('account.sessions.revoke')}
                </button>
              )}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function PasswordInput({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-slate-500 mb-1 block">{label}</span>
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="new-password"
        className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {hint && <span className="text-[11px] text-slate-400 mt-1 block">{hint}</span>}
    </label>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof UserIcon;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 rounded-lg bg-blue-50">
          <Icon size={18} className="text-blue-600" />
        </div>
        <h3 className="text-lg font-semibold text-slate-800">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 border-b border-slate-100 last:border-0 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800 font-medium text-right break-words">{value}</span>
    </div>
  );
}

function EditableInput({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block border-b border-slate-100 pb-2">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </label>
  );
}
