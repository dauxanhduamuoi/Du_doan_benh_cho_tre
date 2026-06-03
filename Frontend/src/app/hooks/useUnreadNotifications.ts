import { useEffect, useState } from 'react';
import { loadNotifications, refreshRiskNotifications } from '@/lib/notifications';

export function useUnreadNotifications(active: boolean) {
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    let alive = true;
    const recalc = () => {
      if (!alive) return;
      setUnreadCount(loadNotifications().filter((n) => !n.read).length);
    };

    recalc();
    refreshRiskNotifications().then(recalc).catch(() => undefined);

    const onStorage = (e: StorageEvent) => {
      if (e.key === 'sd_notifications') recalc();
    };
    window.addEventListener('storage', onStorage);

    const interval = setInterval(() => {
      refreshRiskNotifications().then(recalc).catch(() => undefined);
    }, 60_000);

    return () => {
      alive = false;
      window.removeEventListener('storage', onStorage);
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!active) return undefined;
    const timer = setTimeout(() => {
      setUnreadCount(loadNotifications().filter((n) => !n.read).length);
    }, 300);
    return () => clearTimeout(timer);
  }, [active]);

  return unreadCount;
}
