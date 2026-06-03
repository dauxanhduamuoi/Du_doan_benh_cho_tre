import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bell,
  BellOff,
  AlertTriangle,
  CheckCircle2,
  Info,
  TrendingUp,
  Upload,
  RefreshCcw,
  Loader2,
  Trash2,
  CheckCheck,
  X,
} from 'lucide-react';
import {
  clearAll,
  loadNotifications,
  markAllRead,
  markRead,
  refreshRiskNotifications,
  removeNotification,
  type AppNotification,
  type NotificationType,
} from '@/lib/notifications';
import { useT } from '@/lib/i18n';

const TYPE_ICONS: Record<NotificationType, typeof Bell> = {
  'high-risk': AlertTriangle,
  forecast: TrendingUp,
  import: Upload,
  system: Info,
};

type Filter = 'all' | 'unread' | NotificationType;

export default function NotificationsPanel() {
  const t = useT();
  const [items, setItems] = useState<AppNotification[]>(() => loadNotifications());
  const [filter, setFilter] = useState<Filter>('all');
  const [refreshing, setRefreshing] = useState(false);
  const [lastSync, setLastSync] = useState<string | null>(null);

  const reload = useCallback(() => {
    setItems(loadNotifications());
  }, []);

  useEffect(() => {
    (async () => {
      setRefreshing(true);
      try {
        await refreshRiskNotifications();
        reload();
        setLastSync(new Date().toLocaleTimeString());
      } finally {
        setRefreshing(false);
      }
    })();
  }, [reload]);

  const filtered = useMemo(() => {
    return items.filter((n) => {
      if (filter === 'all') return true;
      if (filter === 'unread') return !n.read;
      return n.type === filter;
    });
  }, [items, filter]);

  const unread = useMemo(() => items.filter((n) => !n.read).length, [items]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshRiskNotifications();
      reload();
      setLastSync(new Date().toLocaleTimeString());
    } finally {
      setRefreshing(false);
    }
  }

  function handleMarkAll() {
    markAllRead();
    reload();
  }

  function handleClear() {
    if (!confirm(t('notifications.confirmClear'))) return;
    clearAll();
    reload();
  }

  function handleRead(id: string) {
    markRead(id);
    reload();
  }

  function handleRemove(id: string) {
    removeNotification(id);
    reload();
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <StatCard
          icon={Bell}
          label={t('notifications.total')}
          value={items.length}
          iconBg="bg-blue-100"
          iconColor="text-blue-600"
          borderColor="border-l-blue-500"
        />
        <StatCard
          icon={AlertTriangle}
          label={t('notifications.unread')}
          value={unread}
          iconBg="bg-red-100"
          iconColor="text-red-600"
          borderColor="border-l-red-500"
        />
        <StatCard
          icon={TrendingUp}
          label={t('notifications.highRisk')}
          value={items.filter((n) => n.type === 'high-risk').length}
          iconBg="bg-amber-100"
          iconColor="text-amber-600"
          borderColor="border-l-amber-500"
        />
        <StatCard
          icon={Info}
          label={t('notifications.system')}
          value={items.filter((n) => n.type === 'system').length}
          iconBg="bg-emerald-100"
          iconColor="text-emerald-600"
          borderColor="border-l-emerald-500"
        />
      </div>

      {/* Action bar */}
      <div className="bg-white rounded-xl p-4 border border-slate-200 shadow-sm flex flex-wrap items-center gap-2">
        <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>
          {t('notifications.total')}
        </FilterChip>
        <FilterChip active={filter === 'unread'} onClick={() => setFilter('unread')}>
          {t('notifications.unread')}
          {unread > 0 && (
            <span className="ml-1 text-[10px] bg-red-500 text-white px-1.5 rounded-full">{unread}</span>
          )}
        </FilterChip>
        {(['high-risk', 'forecast', 'import', 'system'] as NotificationType[]).map((type) => (
          <FilterChip key={type} active={filter === type} onClick={() => setFilter(type)}>
            {t(`notifications.type.${type}`)}
          </FilterChip>
        ))}

        <div className="ml-auto flex items-center gap-2">
          {lastSync && (
            <span className="text-xs text-slate-400 hidden md:inline">
              {t('notifications.syncedAt')} {lastSync}
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
            {t('notifications.sync')}
          </button>
          <button
            onClick={handleMarkAll}
            disabled={unread === 0}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            <CheckCheck size={14} />
            {t('notifications.markAll')}
          </button>
          <button
            onClick={handleClear}
            disabled={items.length === 0}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white border border-red-200 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40"
          >
            <Trash2 size={14} />
            {t('notifications.clearAll')}
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="bg-white rounded-xl border border-dashed border-slate-200 p-10 text-center text-slate-500">
          <BellOff className="mx-auto mb-3 text-slate-300" size={32} />
          <p className="text-sm">{t('notifications.empty.title')}</p>
          <p className="text-xs text-slate-400 mt-1">{t('notifications.empty.desc')}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((n) => (
            <NotificationRow
              key={n.id}
              item={n}
              typeLabel={t(`notifications.type.${n.type}`)}
              onRead={() => handleRead(n.id)}
              onRemove={() => handleRemove(n.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function NotificationRow({
  item,
  typeLabel,
  onRead,
  onRemove,
}: {
  item: AppNotification;
  typeLabel: string;
  onRead: () => void;
  onRemove: () => void;
}) {
  const Icon = TYPE_ICONS[item.type];
  const severityRing =
    item.severity === 'critical'
      ? 'ring-red-200 border-red-200 bg-red-50'
      : item.severity === 'warning'
      ? 'ring-amber-200 border-amber-200 bg-amber-50'
      : 'ring-slate-100 border-slate-200 bg-white';

  const iconColor =
    item.severity === 'critical' ? 'text-red-600' : item.severity === 'warning' ? 'text-amber-600' : 'text-blue-600';

  return (
    <li
      className={`rounded-xl border shadow-sm px-4 py-3 flex items-start gap-3 ${severityRing} ${
        !item.read ? 'ring-1' : ''
      }`}
    >
      <div className="p-2 rounded-lg bg-white border border-slate-200 shrink-0">
        <Icon size={18} className={iconColor} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h4 className={`text-sm ${item.read ? 'font-medium text-slate-700' : 'font-semibold text-slate-900'}`}>
            {item.title}
          </h4>
          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
            {typeLabel}
          </span>
          {!item.read && <span className="w-2 h-2 rounded-full bg-red-500" />}
        </div>
        {item.description && (
          <p className="text-sm text-slate-600 mt-0.5 break-words">{item.description}</p>
        )}
        <p className="text-[11px] text-slate-400 mt-1">
          {new Date(item.createdAt).toLocaleString()}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {!item.read && (
          <button
            onClick={onRead}
            className="p-1.5 rounded-md text-slate-500 hover:bg-white hover:text-emerald-600"
          >
            <CheckCircle2 size={14} />
          </button>
        )}
        <button
          onClick={onRemove}
          className="p-1.5 rounded-md text-slate-500 hover:bg-white hover:text-red-600"
        >
          <X size={14} />
        </button>
      </div>
    </li>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  iconBg,
  iconColor,
  borderColor,
}: {
  icon: typeof Bell;
  label: string;
  value: number;
  iconBg: string;
  iconColor: string;
  borderColor: string;
}) {
  return (
    <div
      className={`bg-white rounded-xl p-5 border border-slate-200 border-l-4 ${borderColor} shadow-sm hover:shadow-md transition-shadow duration-200`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="text-3xl font-bold text-slate-800 mt-1">{value}</p>
        </div>
        <div className={`p-3 rounded-xl ${iconBg}`}>
          <Icon className={iconColor} size={22} />
        </div>
      </div>
    </div>
  );
}

function FilterChip({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-full border transition-all ${
        active
          ? 'bg-blue-600 border-blue-600 text-white'
          : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
      }`}
    >
      {children}
    </button>
  );
}
