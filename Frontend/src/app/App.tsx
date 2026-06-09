import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronRight,
  Bell,
  Menu,
  ChevronLeft,
  LogOut,
  Loader2,
  User as UserIcon,
  Settings as SettingsIcon,
} from 'lucide-react';
import AppPages, { ParentPortalPage } from './AppPages';
import LoginPage from './components/LoginPage';
import LoadingFallback from './components/LoadingFallback';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useUnreadNotifications } from './hooks/useUnreadNotifications';
import { canUse, getBottomNavItems, getMainNavItems, TAB_PERMISSIONS, type TabType } from './navigation';
import { useI18n, useT } from '@/lib/i18n';

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function AppShell() {
  const { user, logout } = useAuth();
  const t = useT();
  const { lang } = useI18n();
  const [activeTab, setActiveTab] = useState<TabType>('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  const unreadCount = useUnreadNotifications(activeTab === 'notifications');

  const allMenuItems = useMemo(() => getMainNavItems(t), [t]);

  const menuItems = useMemo(
    () => allMenuItems.filter((item) => canUse(user, TAB_PERMISSIONS[item.id])),
    [allMenuItems, user],
  );

  const bottomItems = useMemo(() => getBottomNavItems(t), [t]);

  const displayName = user?.full_name || user?.username || 'User';
  const roleLabel = user?.role === 'admin' ? t('user.adminRole') : t('user.staffRole');
  const confirmLogout = () => {
    if (window.confirm(t('sidebar.logoutConfirm'))) {
      logout();
    }
  };

  useEffect(() => {
    if (activeTab === 'settings' || activeTab === 'account' || activeTab === 'notifications') return;
    if (!canUse(user, TAB_PERMISSIONS[activeTab])) {
      setActiveTab(menuItems[0]?.id ?? 'settings');
    }
  }, [activeTab, menuItems, user]);

  // Đóng user menu khi click ra ngoài
  useEffect(() => {
    if (!userMenuOpen) return;
    function onClick(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [userMenuOpen]);

  const pageTitle = useMemo(() => {
    const all = [...menuItems, ...bottomItems];
    return all.find((x) => x.id === activeTab)?.label ?? '';
  }, [activeTab, menuItems, bottomItems]);

  return (
    <div className="size-full flex bg-slate-100">
      {/* Sidebar */}
      <aside
        className={`${sidebarOpen ? 'w-64' : 'w-[72px]'} bg-white border-r border-slate-200 flex flex-col transition-all duration-300 ease-in-out shrink-0 shadow-sm`}
      >
        <div className="p-4 border-b border-slate-200">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shrink-0">
              <span className="text-white font-bold text-sm">{t('brand.logo')}</span>
            </div>
            {sidebarOpen && (
              <div className="overflow-hidden">
                <h1 className="font-bold text-slate-800 text-sm leading-tight truncate">{t('brand.name')}</h1>
                <p className="text-[11px] text-slate-400 truncate">{t('brand.tagline')}</p>
              </div>
            )}
          </div>
        </div>

        <nav className="flex-1 p-3">
          <ul className="space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              const badge = item.id === 'notifications' && unreadCount > 0 ? unreadCount : 0;
              return (
                <li key={item.id}>
                  <button
                    onClick={() => setActiveTab(item.id)}
                    title={!sidebarOpen ? item.label : undefined}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150 ${
                      isActive
                        ? 'bg-blue-600 text-white shadow-md shadow-blue-200'
                        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
                    }`}
                  >
                    <div className="relative shrink-0">
                      <Icon size={20} />
                      {badge > 0 && !sidebarOpen && (
                        <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[10px] font-bold bg-red-500 text-white flex items-center justify-center ring-2 ring-white">
                          {badge > 9 ? '9+' : badge}
                        </span>
                      )}
                    </div>
                    {sidebarOpen && (
                      <>
                        <span className="flex-1 text-left text-sm font-medium">{item.label}</span>
                        {badge > 0 && (
                          <span
                            className={`min-w-[18px] h-5 px-1.5 text-[10px] font-bold rounded-full flex items-center justify-center ${
                              isActive ? 'bg-white text-red-600' : 'bg-red-500 text-white'
                            }`}
                          >
                            {badge > 99 ? '99+' : badge}
                          </span>
                        )}
                        {isActive && badge === 0 && <ChevronRight size={16} className="opacity-70" />}
                      </>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="p-3 border-t border-slate-200 space-y-1">
          {bottomItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                title={!sidebarOpen ? item.label : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
                }`}
              >
                <Icon size={20} className="shrink-0" />
                {sidebarOpen && <span className="text-sm font-medium">{item.label}</span>}
              </button>
            );
          })}
          <button
            onClick={confirmLogout}
            title={!sidebarOpen ? t('sidebar.logout') : undefined}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-slate-500 hover:bg-red-50 hover:text-red-600 transition-colors"
          >
            <LogOut size={20} className="shrink-0" />
            {sidebarOpen && <span className="text-sm font-medium">{t('sidebar.logout')}</span>}
          </button>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            {sidebarOpen ? <ChevronLeft size={20} className="shrink-0" /> : <Menu size={20} className="shrink-0" />}
            {sidebarOpen && <span className="text-sm">{t('sidebar.collapse')}</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Top Bar */}
        <header className="relative z-50 bg-white border-b border-slate-200 px-6 py-3 shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-800">{pageTitle}</h2>
              <p className="text-xs text-slate-400">
                {t('topbar.lastUpdate')}: {new Date().toLocaleDateString(lang === 'vi' ? 'vi-VN' : 'en-US')}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setActiveTab('notifications')}
                title={t('sidebar.notifications')}
                className="relative p-2 hover:bg-slate-100 rounded-xl transition-colors"
              >
                <Bell size={20} className="text-slate-500" />
                {unreadCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 text-[10px] font-bold bg-red-500 text-white rounded-full flex items-center justify-center ring-2 ring-white">
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </button>
              <div className="h-8 w-px bg-slate-200 hidden md:block" />

              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setUserMenuOpen((v) => !v)}
                  className="relative z-50 flex items-center gap-3 rounded-xl px-1 py-1 pr-2 hover:bg-slate-100 transition-colors"
                >
                  <div className="text-right hidden md:block">
                    <p className="text-sm font-medium text-slate-700">{displayName}</p>
                    <p className="text-[11px] text-slate-400">{roleLabel}</p>
                  </div>
                  <div className="w-9 h-9 bg-gradient-to-br from-blue-400 to-blue-600 rounded-full flex items-center justify-center ring-2 ring-blue-100">
                    <span className="text-white font-semibold text-xs">{initialsOf(displayName)}</span>
                  </div>
                </button>
                {userMenuOpen && (
                  <div className="absolute right-0 z-[100] mt-2 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
                    <div className="px-4 py-3 border-b border-slate-100">
                      <p className="text-sm font-semibold text-slate-800 truncate">{displayName}</p>
                      <p className="text-xs text-slate-500 truncate">@{user?.username}</p>
                    </div>
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        setActiveTab('account');
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                    >
                      <UserIcon size={14} />
                      {t('user.myAccount')}
                    </button>
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        setActiveTab('settings');
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                    >
                      <SettingsIcon size={14} />
                      {t('user.settings')}
                    </button>
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        confirmLogout();
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                    >
                      <LogOut size={14} />
                      {t('user.logout')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 overflow-auto p-6">
          <AppPages activeTab={activeTab} />
        </div>
      </main>
    </div>
  );
}

function AuthGate() {
  const { user, loading } = useAuth();
  const t = useT();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="flex items-center gap-2 text-slate-500">
          <Loader2 className="animate-spin" size={18} />
          <span>{t('auth.restoring')}</span>
        </div>
      </div>
    );
  }

  if (!user) return <LoginPage />;
  return <AppShell />;
}

export default function App() {
  const publicPath = window.location.pathname.toLowerCase().replace(/\/+$/, '') || '/';
  if (publicPath === '/phu-huynh' || publicPath === '/parents') {
    return (
      <Suspense fallback={<LoadingFallback fullPage />}>
        <ParentPortalPage />
      </Suspense>
    );
  }

  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
