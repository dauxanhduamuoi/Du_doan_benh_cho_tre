import { useCallback, useEffect, useState } from 'react';
import type { CurrentUser } from '@/lib/api';
import { canAccessTab, type TabType } from './navigation';

export const ADMIN_SECTION_QUERY_KEY = 'section';

const ADMIN_SECTION_IDS: readonly TabType[] = [
  'dashboard',
  'data-import',
  'seasonal',
  'age-analysis',
  'monthly-disease-analysis',
  'gender-analysis',
  'disease-trend-analysis',
  'forecast',
  'weather-risk',
  'medical-knowledge',
  'areas',
  'reports',
  'notifications',
  'settings',
  'account',
];

function isAdminSection(value: string | null): value is TabType {
  return value !== null && ADMIN_SECTION_IDS.includes(value as TabType);
}

export function resolveAdminSection(
  search: string,
  user: CurrentUser | null | undefined,
  fallback: TabType = 'dashboard',
): TabType {
  const requested = new URLSearchParams(search).get(ADMIN_SECTION_QUERY_KEY);
  if (isAdminSection(requested) && canAccessTab(user, requested)) return requested;
  return canAccessTab(user, fallback) ? fallback : 'settings';
}

export function useAdminSectionNavigation(
  user: CurrentUser | null | undefined,
  fallback: TabType = 'dashboard',
) {
  const resolveCurrent = useCallback(
    () => resolveAdminSection(window.location.search, user, fallback),
    [fallback, user],
  );
  const [activeTab, setActiveTab] = useState<TabType>(resolveCurrent);

  useEffect(() => {
    const syncFromUrl = () => setActiveTab(resolveCurrent());
    syncFromUrl();
    window.addEventListener('popstate', syncFromUrl);
    return () => window.removeEventListener('popstate', syncFromUrl);
  }, [resolveCurrent]);

  const navigateToTab = useCallback((requested: TabType) => {
    const next = canAccessTab(user, requested)
      ? requested
      : resolveAdminSection('', user, fallback);
    const url = new URL(window.location.href);
    url.searchParams.set(ADMIN_SECTION_QUERY_KEY, next);
    window.history.pushState(window.history.state, '', url);
    setActiveTab(next);
  }, [fallback, user]);

  return { activeTab, navigateToTab };
}
