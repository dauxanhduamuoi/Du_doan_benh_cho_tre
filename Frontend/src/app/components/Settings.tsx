import { useEffect, useState } from 'react';
import {
  Settings as SettingsIcon,
  Monitor,
  Moon,
  Palette,
  Sun,
  Languages,
  Database,
  Bell,
  Save,
  RotateCcw,
  CheckCircle2,
  Users,
  Plus,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  KeyRound,
  Download,
} from 'lucide-react';
import * as api from '@/lib/api';
import {
  defaultPreferences,
  loadPreferences,
  savePreferences,
  type UserPreferences,
} from '@/lib/preferences';
import { applyTheme } from '@/lib/theme';
import { useI18n } from '@/lib/i18n';
import { languageOptions } from '@/i18n/resources';
import { useAuth } from '../contexts/AuthContext';

export default function Settings() {
  const { user } = useAuth();
  const { t, setLang } = useI18n();
  const [prefs, setPrefs] = useState<UserPreferences>(() => loadPreferences());
  const [saved, setSaved] = useState(false);

  // Admin state
  const [users, setUsers] = useState<api.AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);

  const [availableRoles, setAvailableRoles] = useState<string[]>(['admin', 'staff']);
  const [permissionDefs, setPermissionDefs] = useState<api.PermissionDef[]>([]);
  const [defaultStaffPermissions, setDefaultStaffPermissions] = useState<string[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [savingPermissions, setSavingPermissions] = useState(false);
  const [newPermissions, setNewPermissions] = useState<string[]>([]);
  const [resetPassword, setResetPassword] = useState('');
  const [resetResult, setResetResult] = useState<string | null>(null);

  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newFullName, setNewFullName] = useState('');
  const [newRole, setNewRole] = useState<string>('staff');
  const [newPosition, setNewPosition] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [bulkPrefix, setBulkPrefix] = useState('nv');
  const [bulkCount, setBulkCount] = useState(5);
  const [bulkPassword, setBulkPassword] = useState('');
  const [bulkRole, setBulkRole] = useState('staff');
  const [bulkFullNamePrefix, setBulkFullNamePrefix] = useState('');
  const [bulkPosition, setBulkPosition] = useState('');
  const [bulkPermissions, setBulkPermissions] = useState<string[]>([]);
  const [bulkCreating, setBulkCreating] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  const isAdmin = user?.role === 'admin';
  const canAdmin = (code: string) => {
    if (!isAdmin || !user) return false;
    if (user.permissions.length === 0) return true;
    return user.permissions.includes(code);
  };

  const visiblePermissionDefs = (role: string) =>
    role === 'admin'
      ? permissionDefs.filter((p) => p.code.startsWith('admin.'))
      : permissionDefs.filter((p) => p.code.startsWith('feature.'));
  const adminDefaultPermissions = permissionDefs.filter((p) => p.code.startsWith('admin.')).map((p) => p.code);
  const defaultPermissionsForRole = (role: string) =>
    role === 'admin' ? adminDefaultPermissions : defaultStaffPermissions;

  // Map role-key → label hiển thị theo i18n hiện tại. Role không có key
  // tương ứng (ví dụ admin tự thêm `nurse`) sẽ tự fallback về tên gốc.
  const roleLabels: Record<string, string> = {};
  for (const r of availableRoles) {
    roleLabels[r] = r === 'admin' ? 'Admin' : 'Người dùng hệ thống';
  }

  useEffect(() => {
    if (!isAdmin) return;
    loadUsers();
    api
      .listRoles()
      .then((r) => setAvailableRoles(r.roles))
      .catch(() => undefined);
    api
      .listPermissions()
      .then((r) => {
        setPermissionDefs(r.permissions);
        setDefaultStaffPermissions(r.default_staff_permissions);
        const adminDefaults = r.permissions.filter((p) => p.code.startsWith('admin.')).map((p) => p.code);
        setNewPermissions(newRole === 'admin' ? adminDefaults : r.default_staff_permissions);
        setBulkPermissions(bulkRole === 'admin' ? adminDefaults : r.default_staff_permissions);
      })
      .catch(() => undefined);
  }, [isAdmin]);

  async function loadUsers() {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const rows = await api.listUsers();
      setUsers(rows);
    } catch (e) {
      setUsersError(e instanceof Error ? e.message : String(e));
    } finally {
      setUsersLoading(false);
    }
  }

  function updatePref<K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) {
    setPrefs((p) => {
      const next = { ...p, [key]: value };
      // Áp dụng ngay với theme/language để user thấy hiệu ứng tức thì.
      if (key === 'theme') {
        applyTheme(next.theme);
      }
      if (key === 'language') {
        setLang(next.language);
      }
      // Luôn lưu ngay để các tab khác đồng bộ qua storage event.
      savePreferences(next);
      return next;
    });
    setSaved(false);
  }

  function handleSave() {
    savePreferences(prefs);
    applyTheme(prefs.theme);
    setLang(prefs.language);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function handleReset() {
    const next = { ...defaultPreferences };
    setPrefs(next);
    savePreferences(next);
    applyTheme(next.theme);
    setLang(next.language);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleCreateUser() {
    setCreateError(null);
    if (!newUsername.trim() || !newPassword) {
      setCreateError(t('settings.users.required'));
      return;
    }
    setCreating(true);
    try {
      await api.createUser({
        username: newUsername.trim(),
        password: newPassword,
        full_name: newFullName.trim() || undefined,
        role: newRole,
        position: newPosition.trim() || undefined,
        permissions: newPermissions,
      });
      setNewUsername('');
      setNewPassword('');
      setNewFullName('');
      setNewRole('staff');
      setNewPosition('');
      setNewPermissions(defaultStaffPermissions);
      await loadUsers();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  function selectedUser() {
    return users.find((u) => u.id === selectedUserId) ?? null;
  }

  function togglePermission(current: string[], code: string) {
    return current.includes(code) ? current.filter((x) => x !== code) : [...current, code].sort();
  }

  async function saveSelectedUserPermissions() {
    const target = selectedUser();
    if (!target) return;
    setSavingPermissions(true);
    setUsersError(null);
    try {
      const updated = await api.updateUserPermissions(target.id, target.permissions);
      setUsers((cur) => cur.map((u) => (u.id === updated.id ? updated : u)));
    } catch (e) {
      setUsersError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingPermissions(false);
    }
  }

  async function handleResetPassword(target: api.AdminUser) {
    if (!resetPassword || resetPassword.length < 6) {
      setResetResult('Mật khẩu mới phải có ít nhất 6 ký tự.');
      return;
    }
    setResetResult(null);
    try {
      const result = await api.resetUserPassword(target.id, resetPassword);
      setResetResult(`Đã reset mật khẩu cho ${result.username}.`);
      setResetPassword('');
    } catch (e) {
      setResetResult(e instanceof Error ? e.message : String(e));
    }
  }

  function downloadCreatedAccounts(rows: Array<{ username: string; password: string; role: string }>) {
    const esc = (value: string) =>
      String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    const html = `<!doctype html><html><head><meta charset="utf-8" /></head><body><table><thead><tr><th>username</th><th>password</th><th>role</th></tr></thead><tbody>${rows
      .map((row) => `<tr><td>${esc(row.username)}</td><td>${esc(row.password)}</td><td>${esc(row.role)}</td></tr>`)
      .join('')}</tbody></table></body></html>`;
    const blob = new Blob([html], { type: 'application/vnd.ms-excel;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tai-khoan-tao-hang-loat-${new Date().toISOString().slice(0, 10)}.xls`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleBulkCreate() {
    setBulkError(null);
    if (bulkPermissions.length === 0) {
      setBulkError('Tạo hàng loạt bắt buộc phải chọn ít nhất một quyền.');
      return;
    }
    setBulkCreating(true);
    try {
      const result = await api.bulkCreateUsers({
        username_prefix: bulkPrefix,
        count: bulkCount,
        password: bulkPassword,
        role: bulkRole,
        permissions: bulkPermissions,
        full_name_prefix: bulkFullNamePrefix.trim() || undefined,
        position: bulkPosition.trim() || undefined,
      });
      downloadCreatedAccounts(result.created);
      await loadUsers();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : String(e));
    } finally {
      setBulkCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      <Section icon={SettingsIcon} title={t('settings.theme.title')} subtitle={t('settings.theme.subtitle')}>
        <FieldGroup label={t('settings.theme.label')}>
          <div className="grid grid-cols-2 gap-2 max-w-xl sm:grid-cols-4">
            <ThemeOption
              active={prefs.theme === 'light'}
              icon={Sun}
              label={t('settings.theme.light')}
              onClick={() => updatePref('theme', 'light')}
            />
            <ThemeOption
              active={prefs.theme === 'dark'}
              icon={Moon}
              label={t('settings.theme.dark')}
              onClick={() => updatePref('theme', 'dark')}
            />
            <ThemeOption
              active={prefs.theme === 'system'}
              icon={Monitor}
              label={t('settings.theme.system')}
              onClick={() => updatePref('theme', 'system')}
            />
            <ThemeOption
              active={prefs.theme === 'multicolor'}
              icon={Palette}
              label={t('settings.theme.multicolor')}
              onClick={() => updatePref('theme', 'multicolor')}
              tone="multicolor"
            />
          </div>
          <p className="text-[11px] text-slate-400 mt-2">{t('settings.theme.note')}</p>
        </FieldGroup>

        <FieldGroup label={t('settings.language.label')} icon={Languages}>
          <div className="flex flex-wrap gap-2">
            {languageOptions.map((option) => (
              <button
                key={option.code}
                type="button"
                onClick={() => updatePref('language', option.code)}
                className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition-colors ${
                  prefs.language === option.code
                    ? 'border-blue-500 bg-blue-600 text-white shadow-sm shadow-blue-100'
                    : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                {prefs.language === option.code && <CheckCircle2 size={16} />}
                {option.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">{t('settings.language.note')}</p>
        </FieldGroup>
      </Section>


      <Section icon={Bell} title={t('settings.notify.title')} subtitle={t('settings.notify.subtitle')}>
        <ToggleRow
          label={t('settings.notify.highRisk')}
          description={t('settings.notify.highRisk.desc')}
          checked={prefs.notifyHighRisk}
          onChange={(v) => updatePref('notifyHighRisk', v)}
        />
        <ToggleRow
          label={t('settings.notify.forecast')}
          description={t('settings.notify.forecast.desc')}
          checked={prefs.notifyForecast}
          onChange={(v) => updatePref('notifyForecast', v)}
        />
        <ToggleRow
          label={t('settings.notify.import')}
          description={t('settings.notify.import.desc')}
          checked={prefs.notifyImport}
          onChange={(v) => updatePref('notifyImport', v)}
        />
      </Section>

      <div className="flex gap-3">
        <button
          onClick={handleSave}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white font-medium hover:bg-blue-700 shadow-sm shadow-blue-200"
        >
          <Save size={16} />
          {t('settings.save')}
        </button>
        <button
          onClick={handleReset}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
        >
          <RotateCcw size={16} />
          {t('settings.reset')}
        </button>
        {saved && (
          <span className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm">
            <CheckCircle2 size={14} /> {t('settings.saved')}
          </span>
        )}
      </div>

      {/* Admin */}
      {isAdmin ? (
        <Section icon={Users} title={t('settings.users.title')} subtitle={t('settings.users.subtitle')}>
          {usersError && (
            <div className="mb-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              {usersError}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 border border-slate-200 rounded-lg overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 bg-slate-50 border-b border-slate-200">
                <span className="text-sm font-medium text-slate-700">
                  {users.length} {t('settings.users.count')}
                </span>
                <button
                  onClick={loadUsers}
                  disabled={usersLoading}
                  className="text-xs text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
                >
                  {usersLoading ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                  {t('common.refresh')}
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 border-b border-slate-200">
                      <th className="py-2 px-3">{t('settings.users.colUsername')}</th>
                      <th className="py-2 px-3">{t('settings.users.colFullName')}</th>
                      <th className="py-2 px-3">{t('settings.users.colRole')}</th>
                      <th className="py-2 px-3">{t('settings.users.colStatus')}</th>
                      <th className="py-2 px-3 text-right">{t('settings.users.colAction')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.length === 0 && !usersLoading && (
                      <tr>
                        <td colSpan={5} className="py-6 text-center text-slate-400">
                          {t('common.noData')}
                        </td>
                      </tr>
                    )}
                    {users.map((u) => (
                      <tr key={u.id} className="border-b border-slate-100 last:border-0">
                        <td className="py-2 px-3 font-medium text-slate-700">{u.username}</td>
                        <td className="py-2 px-3 text-slate-600">{u.full_name ?? '—'}</td>
                        <td className="py-2 px-3 w-44">
                          <RoleSelect
                            value={u.role}
                            options={availableRoles}
                            labels={roleLabels}
                            disabled={!canAdmin('admin.assign_permissions')}
                            onChange={async (next) => {
                              try {
                                const updated = await api.updateUserRole(u.id, next);
                                setUsers((cur) => cur.map((x) => (x.id === u.id ? updated : x)));
                              } catch (err) {
                                setUsersError(err instanceof Error ? err.message : String(err));
                              }
                            }}
                          />
                        </td>
                        <td className="py-2 px-3">
                          {u.is_active ? (
                            <span className="inline-block px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-700 border border-emerald-200">
                              {t('common.active')}
                            </span>
                          ) : (
                            <span className="inline-block px-2 py-0.5 rounded-full text-xs bg-red-50 text-red-700 border border-red-200">
                              {t('common.inactive')}
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-right">
                          <div className="flex flex-wrap justify-end gap-2">
                          {canAdmin('admin.assign_permissions') && (
                            <button
                              onClick={() => setSelectedUserId(u.id)}
                              className="text-xs text-blue-600 hover:text-blue-700"
                            >
                              Phân quyền
                            </button>
                          )}
                          {canAdmin('admin.reset_password') && (
                            <button
                              onClick={() => setResetUserId(u.id)}
                              className="text-xs text-slate-600 hover:text-blue-700"
                            >
                              Reset
                            </button>
                          )}
                          {u.username !== user?.username && canAdmin('admin.toggle_user') && (
                            <button
                              onClick={async () => {
                                try {
                                  const updated = await api.updateUserActive(u.id, !u.is_active);
                                  setUsers((cur) => cur.map((x) => (x.id === u.id ? updated : x)));
                                } catch (err) {
                                  setUsersError(err instanceof Error ? err.message : String(err));
                                }
                              }}
                              className="text-xs text-slate-600 hover:text-red-600"
                            >
                              {u.is_active ? t('settings.users.disable') : t('settings.users.enable')}
                            </button>
                          )}
                          {u.username !== user?.username && canAdmin('admin.delete_user') && (
                            <button
                              onClick={async () => {
                                if (!window.confirm(`Xóa tài khoản ${u.username}?`)) return;
                                try {
                                  await api.deleteUser(u.id);
                                  setUsers((cur) => cur.filter((x) => x.id !== u.id));
                                } catch (err) {
                                  setUsersError(err instanceof Error ? err.message : String(err));
                                }
                              }}
                              className="text-xs text-red-600 hover:text-red-700"
                            >
                              Xóa
                            </button>
                          )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
              <h4 className="font-medium text-slate-800 flex items-center gap-2">
                <Plus size={16} /> {t('settings.users.create')}
              </h4>
              <Input
                label={t('settings.users.inputUsername')}
                value={newUsername}
                onChange={setNewUsername}
                placeholder={t('settings.users.usernameHint')}
              />
              <Input
                label={t('settings.users.inputPassword')}
                value={newPassword}
                onChange={setNewPassword}
                type="password"
                placeholder={t('settings.users.passwordHint')}
              />
              <Input
                label={t('settings.users.inputFullName')}
                value={newFullName}
                onChange={setNewFullName}
                placeholder={t('settings.users.fullNameHint')}
              />
              <div>
                <label className="text-xs text-slate-500 mb-1 block">{t('settings.users.inputRole')}</label>
                <RoleSelect
                  value={newRole}
                  options={availableRoles}
                  labels={roleLabels}
                  onChange={(role) => {
                    setNewRole(role);
                    setNewPermissions(defaultPermissionsForRole(role));
                  }}
                />
              </div>
              <Input
                label="Chức vụ"
                value={newPosition}
                onChange={setNewPosition}
                placeholder="Bác sĩ, điều dưỡng, giám đốc..."
              />
              <PermissionChecklist
                title="Phân quyền tài khoản"
                permissions={visiblePermissionDefs(newRole)}
                selected={newPermissions}
                onToggle={(code) => setNewPermissions((cur) => togglePermission(cur, code))}
              />
              {createError && (
                <p className="text-xs text-red-600 break-words">{createError}</p>
              )}
              <button
                onClick={handleCreateUser}
                disabled={creating || !canAdmin('admin.create_user')}
                className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
              >
                {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                {t('settings.users.create')}
              </button>
            </div>
          </div>

          {selectedUser() && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4">
              <div className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-xl bg-white p-5 shadow-2xl">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <h4 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
                      <ShieldCheck size={18} /> Phân quyền cho {selectedUser()?.username}
                    </h4>
                    <p className="mt-1 text-xs text-slate-500">
                      Admin luôn dùng được các mục chính. Các quyền quản trị chỉ kiểm soát thao tác nâng cao.
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedUserId(null);
                      setResetPassword('');
                      setResetResult(null);
                    }}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    Đóng
                  </button>
                </div>
            <div>
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <h4 className="mb-3 flex items-center gap-2 font-medium text-slate-800">
                  <ShieldCheck size={16} /> Bảng phân quyền
                </h4>
                <PermissionChecklist
                  title="Quyền được sử dụng"
                  permissions={visiblePermissionDefs(selectedUser()?.role ?? 'staff')}
                  selected={selectedUser()?.permissions ?? []}
                  onToggle={(code) => {
                    const target = selectedUser();
                    if (!target) return;
                    setUsers((cur) =>
                      cur.map((u) =>
                        u.id === target.id ? { ...u, permissions: togglePermission(u.permissions, code) } : u,
                      ),
                    );
                  }}
                />
                <button
                  onClick={saveSelectedUserPermissions}
                  disabled={savingPermissions || !canAdmin('admin.assign_permissions')}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {savingPermissions ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                  Lưu phân quyền
                </button>
              </div>
            </div>
              </div>
            </div>
          )}

          {resetUserId && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4">
              <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <h4 className="flex items-center gap-2 text-lg font-semibold text-slate-800">
                      <KeyRound size={18} /> Reset mật khẩu
                    </h4>
                    <p className="mt-1 text-xs text-slate-500">
                      Tài khoản: {users.find((u) => u.id === resetUserId)?.username}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setResetUserId(null);
                      setResetPassword('');
                      setResetResult(null);
                    }}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    Đóng
                  </button>
                </div>
                <Input
                  label="Mật khẩu mới"
                  value={resetPassword}
                  onChange={setResetPassword}
                  type="password"
                  placeholder="Ít nhất 6 ký tự"
                />
                <button
                  onClick={() => {
                    const target = users.find((u) => u.id === resetUserId);
                    if (target) handleResetPassword(target);
                  }}
                  disabled={!canAdmin('admin.reset_password')}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  <KeyRound size={14} />
                  Reset mật khẩu
                </button>
                {resetResult && <p className="mt-2 text-xs text-slate-600">{resetResult}</p>}
              </div>
            </div>
          )}

          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h4 className="mb-3 flex items-center gap-2 font-medium text-slate-800">
              <Download size={16} /> Tạo hàng loạt tài khoản nhân viên
            </h4>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
              <Input label="Tiền tố username" value={bulkPrefix} onChange={setBulkPrefix} placeholder="nv" />
              <Input label="Số lượng" value={String(bulkCount)} onChange={(v) => setBulkCount(Number(v) || 1)} type="number" />
              <Input label="Mật khẩu chung" value={bulkPassword} onChange={setBulkPassword} type="password" />
              <Input label="Tiền tố họ tên" value={bulkFullNamePrefix} onChange={setBulkFullNamePrefix} placeholder="Nhân viên" />
              <div>
                <label className="mb-1 block text-xs text-slate-500">Vai trò</label>
                <RoleSelect
                  value={bulkRole}
                  options={availableRoles}
                  labels={roleLabels}
                  onChange={(role) => {
                    setBulkRole(role);
                    setBulkPermissions(defaultPermissionsForRole(role));
                  }}
                />
              </div>
            </div>
            <div className="mt-3 max-w-sm">
              <Input label="Chức vụ mặc định" value={bulkPosition} onChange={setBulkPosition} placeholder="Nhân viên, điều dưỡng..." />
            </div>
            <div className="mt-3">
              <PermissionChecklist
                title="Bảng phân quyền bắt buộc cho tạo hàng loạt"
                permissions={visiblePermissionDefs(bulkRole)}
                selected={bulkPermissions}
                onToggle={(code) => setBulkPermissions((cur) => togglePermission(cur, code))}
              />
            </div>
            {bulkError && <p className="mt-2 text-xs text-red-600">{bulkError}</p>}
            <button
              onClick={handleBulkCreate}
              disabled={bulkCreating || !canAdmin('admin.create_user')}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {bulkCreating ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              Tạo và xuất file Excel
            </button>
          </div>
        </Section>
      ) : (
        <Section icon={ShieldAlert} title={t('settings.users.title')} subtitle={t('settings.users.notAdmin')}>
          <p className="text-sm text-slate-500">{t('settings.users.noAccess')}</p>
        </Section>
      )}

      <Section icon={Database} title={t('settings.system.title')} subtitle={t('settings.system.subtitle')}>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <InfoRow label={t('settings.system.backend')} value="FastAPI · http://127.0.0.1:8000" />
          <InfoRow label={t('settings.system.frontend')} value="Vite + React · http://localhost:5173" />
          <InfoRow label={t('settings.system.database')} value="SQLite (seasonal_disease_backend/database.db)" />
          <InfoRow label={t('settings.system.model')} value="app/ml/seasonal_disease_forecast_model.pkl" />
        </dl>
      </Section>
    </div>
  );
}

// ===== UI helpers =====

function Section({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: typeof SettingsIcon;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
      <div className="flex items-start gap-3 mb-5">
        <div className="p-2 rounded-lg bg-blue-50">
          <Icon size={18} className="text-blue-600" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-slate-800 leading-tight">{title}</h3>
          {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function FieldGroup({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon?: typeof SettingsIcon;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5 last:mb-0">
      <div className="flex items-center gap-1.5 mb-2">
        {Icon && <Icon size={14} className="text-slate-500" />}
        <label className="text-sm font-medium text-slate-700">{label}</label>
      </div>
      {children}
    </div>
  );
}

function ThemeOption({
  active,
  icon: Icon,
  label,
  onClick,
  tone = 'default',
}: {
  active: boolean;
  icon: typeof SettingsIcon;
  label: string;
  onClick: () => void;
  tone?: 'default' | 'multicolor';
}) {
  const activeClass =
    tone === 'multicolor'
      ? 'border-sky-300 bg-gradient-to-br from-sky-100 via-emerald-50 to-amber-100 text-sky-800 shadow-md shadow-sky-100'
      : 'border-blue-500 bg-blue-50 text-blue-700';
  const inactiveClass =
    tone === 'multicolor'
      ? 'border-sky-200 bg-gradient-to-br from-white via-sky-50 to-amber-50 text-slate-700 hover:border-sky-300 hover:shadow-sm hover:shadow-sky-100'
      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300';

  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-2 p-4 rounded-xl border transition-all ${
        active ? activeClass : inactiveClass
      }`}
    >
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-xl ${
          tone === 'multicolor'
            ? 'bg-gradient-to-br from-blue-500 via-cyan-400 to-emerald-400 text-white shadow-sm shadow-sky-200'
            : ''
        }`}
      >
        <Icon size={20} />
      </div>
      <span className="text-sm font-medium">{label}</span>
      {tone === 'multicolor' && (
        <span className="mt-1 flex h-1.5 w-16 overflow-hidden rounded-full">
          <span className="flex-1 bg-blue-500" />
          <span className="flex-1 bg-cyan-400" />
          <span className="flex-1 bg-emerald-400" />
          <span className="flex-1 bg-amber-400" />
          <span className="flex-1 bg-rose-500" />
        </span>
      )}
    </button>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-slate-100 last:border-0">
      <div>
        <p className="text-sm font-medium text-slate-700">{label}</p>
        {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors shrink-0 ${
          checked ? 'bg-blue-600' : 'bg-slate-300'
        }`}
        aria-pressed={checked}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}

function PermissionChecklist({
  title,
  permissions,
  selected,
  onToggle,
}: {
  title: string;
  permissions: api.PermissionDef[];
  selected: string[];
  onToggle: (code: string) => void;
}) {
  const groups = permissions.reduce<Record<string, api.PermissionDef[]>>((acc, p) => {
    if (!acc[p.group]) acc[p.group] = [];
    acc[p.group].push(p);
    return acc;
  }, {});

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="space-y-3">
        {Object.entries(groups).map(([group, rows]) => (
          <div key={group}>
            <div className="mb-1 text-xs font-medium text-slate-600">{group}</div>
            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {rows.map((p) => (
                <label key={p.code} className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-slate-50">
                  <input
                    type="checkbox"
                    checked={selected.includes(p.code)}
                    onChange={() => onToggle(p.code)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium text-slate-700">{p.label}</span>
                    <span className="block font-mono text-[10px] text-slate-400">{p.code}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RoleSelect({
  value,
  options,
  labels,
  disabled,
  onChange,
}: {
  value: string;
  options: string[];
  labels: Record<string, string>;
  disabled?: boolean;
  onChange: (value: string) => void | Promise<void>;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => void onChange(event.target.value)}
      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
    >
      {options.map((role) => (
        <option key={role} value={role}>
          {labels[role] ?? role}
        </option>
      ))}
    </select>
  );
}

function Input({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-slate-500 mb-1 block">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </label>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200">
      <span className="text-slate-500 min-w-[110px]">{label}</span>
      <span className="text-slate-700 font-mono text-xs truncate">{value}</span>
    </div>
  );
}
