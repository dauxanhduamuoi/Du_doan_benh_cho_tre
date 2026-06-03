// Lớp sinh thông báo dùng chung cho Dashboard / NotificationsPanel.

import * as api from './api';
import { loadPreferences } from './preferences';

export type NotificationType = 'high-risk' | 'forecast' | 'import' | 'system';
export type NotificationSeverity = 'info' | 'warning' | 'critical';

export interface AppNotification {
  id: string;
  type: NotificationType;
  severity: NotificationSeverity;
  title: string;
  description?: string;
  createdAt: string; // ISO
  read: boolean;
  meta?: Record<string, unknown>;
}

const KEY = 'sd_notifications';
const SEEN_FORECAST_KEY = 'sd_seen_forecasts';

export function loadNotifications(): AppNotification[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    return JSON.parse(raw) as AppNotification[];
  } catch {
    return [];
  }
}

function saveNotifications(items: AppNotification[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items.slice(0, 100)));
  } catch {
    // ignore
  }
}

export function addNotification(n: Omit<AppNotification, 'id' | 'createdAt' | 'read'>): AppNotification {
  const prefs = loadPreferences();
  // Tôn trọng tuỳ chọn thông báo
  if (n.type === 'high-risk' && !prefs.notifyHighRisk) return stubNotification(n);
  if (n.type === 'forecast' && !prefs.notifyForecast) return stubNotification(n);
  if (n.type === 'import' && !prefs.notifyImport) return stubNotification(n);

  const item: AppNotification = {
    id: `n${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    createdAt: new Date().toISOString(),
    read: false,
    ...n,
  };
  const items = [item, ...loadNotifications()];
  saveNotifications(items);
  return item;
}

function stubNotification(n: Omit<AppNotification, 'id' | 'createdAt' | 'read'>): AppNotification {
  // Trả về object đầy đủ để caller dễ dùng, nhưng không lưu.
  return {
    id: `stub-${Date.now()}`,
    createdAt: new Date().toISOString(),
    read: true,
    ...n,
  };
}

export function markRead(id: string) {
  const items = loadNotifications().map((n) => (n.id === id ? { ...n, read: true } : n));
  saveNotifications(items);
}

export function markAllRead() {
  const items = loadNotifications().map((n) => ({ ...n, read: true }));
  saveNotifications(items);
}

export function removeNotification(id: string) {
  saveNotifications(loadNotifications().filter((n) => n.id !== id));
}

export function clearAll() {
  saveNotifications([]);
}

function loadSeenForecasts(): Record<string, true> {
  try {
    const raw = localStorage.getItem(SEEN_FORECAST_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, true>;
  } catch {
    return {};
  }
}

function saveSeenForecasts(seen: Record<string, true>) {
  localStorage.setItem(SEEN_FORECAST_KEY, JSON.stringify(seen));
}

/**
 * Kiểm tra dự báo từ BE và tạo thông báo cho nhóm "Cao".
 * Trả về số thông báo mới được thêm (sau khi đã de-dup theo period + disease).
 */
export async function refreshRiskNotifications(): Promise<number> {
  let added = 0;
  try {
    const rows = await api.getForecastGroupSummary();
    const seen = loadSeenForecasts();

    for (const r of rows) {
      if (r.risk_level !== 'Cao') continue;
      const key = `${r.forecast_period}::${r.disease_group}`;
      if (seen[key]) continue;

      addNotification({
        type: 'high-risk',
        severity: 'critical',
        title: `Rủi ro cao: ${r.disease_group}`,
        description: `Kỳ ${r.forecast_period} · dự báo ${r.predicted_cases} ca (${
          r.change_percent !== null ? `${r.change_percent.toFixed(1)}%` : 'n/a'
        }) · ${r.trend}`,
        meta: {
          forecast_period: r.forecast_period,
          disease_group: r.disease_group,
          predicted_cases: r.predicted_cases,
        },
      });
      seen[key] = true;
      added += 1;
    }

    saveSeenForecasts(seen);
  } catch {
    // silent: BE có thể chưa chạy dự báo
  }
  return added;
}
