import { lazy, Suspense } from 'react';
import LoadingFallback from './components/LoadingFallback';
import type { TabType } from './navigation';

const DashboardOverview = lazy(() => import('./components/DashboardOverview'));
const DataImport = lazy(() => import('./components/DataImport'));
const SeasonalAnalysis = lazy(() => import('./components/SeasonalAnalysis'));
const AgeAnalysis = lazy(() => import('./components/AgeAnalysis'));
const AdvancedAnalytics = lazy(() => import('./components/AdvancedAnalytics'));
const Forecast = lazy(() => import('./components/Forecast'));
const WeatherRisk = lazy(() => import('./components/WeatherRisk'));
const AreaInsights = lazy(() => import('./components/AreaInsights'));
const Reports = lazy(() => import('./components/Reports'));
const NotificationsPanel = lazy(() => import('./components/NotificationsPanel'));
const SettingsPanel = lazy(() => import('./components/Settings'));
const Account = lazy(() => import('./components/Account'));
const MedicalKnowledgeResearchPage = lazy(() => import('./components/medical-knowledge/MedicalKnowledgeResearchPage'));

export const ParentPortalPage = lazy(() => import('./components/ParentPortal'));

export default function AppPages({ activeTab }: { activeTab: TabType }) {
  return (
    <Suspense fallback={<LoadingFallback />}>
      {activeTab === 'dashboard' && <DashboardOverview />}
      {activeTab === 'data-import' && <DataImport />}
      {activeTab === 'seasonal' && <SeasonalAnalysis />}
      {activeTab === 'age-analysis' && <AgeAnalysis />}
      {activeTab === 'monthly-disease-analysis' && <AdvancedAnalytics mode="monthly" />}
      {activeTab === 'gender-analysis' && <AdvancedAnalytics mode="gender" />}
      {activeTab === 'disease-trend-analysis' && <AdvancedAnalytics mode="trend" />}
      {activeTab === 'forecast' && <Forecast />}
      {activeTab === 'weather-risk' && <WeatherRisk />}
      {activeTab === 'medical-knowledge' && <MedicalKnowledgeResearchPage />}
      {activeTab === 'areas' && <AreaInsights />}
      {activeTab === 'reports' && <Reports />}
      {activeTab === 'notifications' && <NotificationsPanel />}
      {activeTab === 'settings' && <SettingsPanel />}
      {activeTab === 'account' && <Account />}
    </Suspense>
  );
}
