import {
  Activity,
  BarChart3,
  BookOpenText,
  CloudSun,
  FileText,
  LayoutDashboard,
  MapPin,
  Settings as SettingsIcon,
  SlidersHorizontal,
  TrendingUp,
  Upload,
  User as UserIcon,
  type LucideIcon,
} from 'lucide-react';
import type { CurrentUser } from '@/lib/api';

export type TabType =
  | 'dashboard'
  | 'data-import'
  | 'seasonal'
  | 'age-analysis'
  | 'monthly-disease-analysis'
  | 'gender-analysis'
  | 'disease-trend-analysis'
  | 'forecast'
  | 'weather-risk'
  | 'medical-knowledge'
  | 'areas'
  | 'reports'
  | 'notifications'
  | 'settings'
  | 'account';

export interface NavItem {
  id: TabType;
  label: string;
  icon: LucideIcon;
}

export const TAB_PERMISSIONS: Partial<Record<TabType, string>> = {
  dashboard: 'feature.dashboard',
  'data-import': 'feature.data_import',
  seasonal: 'feature.seasonal',
  'age-analysis': 'feature.age_analysis',
  'monthly-disease-analysis': 'feature.monthly_disease',
  'gender-analysis': 'feature.gender_analysis',
  'disease-trend-analysis': 'feature.disease_trend',
  forecast: 'feature.forecast',
  'weather-risk': 'feature.weather_risk',
  areas: 'feature.areas',
  reports: 'feature.reports',
};

export const TAB_ROLES: Partial<Record<TabType, readonly string[]>> = {
  'medical-knowledge': ['admin', 'staff'],
};

export function canUse(user: CurrentUser | null | undefined, permission?: string): boolean {
  if (!permission) return true;
  if (!user) return false;
  if (user.role === 'admin') return true;
  return user.permissions.includes(permission);
}

export function canAccessTab(user: CurrentUser | null | undefined, tab: TabType): boolean {
  if (!user) return false;
  const roles = TAB_ROLES[tab];
  if (roles && !roles.includes(user.role)) return false;
  return canUse(user, TAB_PERMISSIONS[tab]);
}

export function getMainNavItems(t: (key: string) => string): NavItem[] {
  return [
    { id: 'dashboard', label: t('sidebar.dashboard'), icon: LayoutDashboard },
    { id: 'data-import', label: t('sidebar.dataImport'), icon: Upload },
    { id: 'seasonal', label: t('sidebar.seasonal'), icon: TrendingUp },
    { id: 'age-analysis', label: t('sidebar.ageAnalysis'), icon: SlidersHorizontal },
    { id: 'monthly-disease-analysis', label: t('sidebar.monthlyDisease'), icon: BarChart3 },
    { id: 'gender-analysis', label: t('sidebar.genderAnalysis'), icon: UserIcon },
    { id: 'disease-trend-analysis', label: t('sidebar.diseaseTrend'), icon: Activity },
    { id: 'forecast', label: t('sidebar.forecast'), icon: Activity },
    { id: 'weather-risk', label: t('sidebar.weatherRisk'), icon: CloudSun },
    { id: 'medical-knowledge', label: t('sidebar.medicalKnowledge'), icon: BookOpenText },
    { id: 'areas', label: t('sidebar.areas'), icon: MapPin },
    { id: 'reports', label: t('sidebar.reports'), icon: FileText },
  ];
}

export function getBottomNavItems(t: (key: string) => string): NavItem[] {
  return [{ id: 'settings', label: t('sidebar.settings'), icon: SettingsIcon }];
}
