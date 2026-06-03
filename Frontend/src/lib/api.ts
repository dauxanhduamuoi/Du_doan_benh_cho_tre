// API client cho Seasonal Disease backend.
// Mọi request đi qua proxy Vite /api → FastAPI ở http://127.0.0.1:8000.

const TOKEN_KEY = 'sd_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

type RequestOptions = RequestInit & { skipAuth?: boolean };

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { skipAuth, headers, ...rest } = options;

  const finalHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...((headers as Record<string, string>) ?? {}),
  };

  if (!skipAuth) {
    const token = getToken();
    if (token) {
      finalHeaders['Authorization'] = `Bearer ${token}`;
    }
  }

  const res = await fetch(path, { ...rest, headers: finalHeaders });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      // ignore parse error
    }
    throw new Error(detail || `Request failed: ${res.status}`);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ===== Auth =====

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.set('username', username);
  form.set('password', password);

  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });

  if (!res.ok) {
    let detail = 'Đăng nhập thất bại';
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  const data = (await res.json()) as LoginResponse;
  setToken(data.access_token);
  return data;
}

export interface CurrentUser {
  id: number;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  permissions: string[];
  birth_date?: string | null;
  gender?: string | null;
  position?: string | null;
}

export function me(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/me');
}

export function logout() {
  setToken(null);
}

export function changePassword(currentPassword: string, newPassword: string) {
  return request<{ message: string }>('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export function updateProfile(payload: {
  full_name?: string | null;
  birth_date?: string | null;
  gender?: string | null;
  position?: string | null;
}): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export interface LoginSessionInfo {
  id: number;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string;
  is_current: boolean;
  revoked_at: string | null;
}

export function listSessions(): Promise<LoginSessionInfo[]> {
  return request<LoginSessionInfo[]>('/api/auth/sessions');
}

export function revokeSession(id: number) {
  return request<{ message: string }>(`/api/auth/sessions/${id}/revoke`, { method: 'POST' });
}

export function revokeOtherSessions() {
  return request<{ revoked: number }>('/api/auth/sessions/revoke-others', { method: 'POST' });
}

// ===== Dashboard =====

export interface OverviewResponse {
  data_type: string;
  total_records: number;
  total_periods: number;
  total_disease_groups: number;
}

export function getOverview(dataType = 'predict_current'): Promise<OverviewResponse> {
  return request<OverviewResponse>(`/api/dashboard/overview?data_type=${encodeURIComponent(dataType)}`);
}

export interface MonthlyStat {
  period: string;
  disease_group: string;
  case_count: number;
}

export interface YearlyCaseStat {
  year: number;
  case_count: number;
  month_count: number;
  months: number[];
  missing_months: number[];
  is_complete_year: boolean;
}

export function getMonthlyStatistics(dataType = 'predict_current'): Promise<MonthlyStat[]> {
  return request<MonthlyStat[]>(
    `/api/dashboard/monthly-statistics?data_type=${encodeURIComponent(dataType)}`,
  );
}

export function getCasesByYear(): Promise<YearlyCaseStat[]> {
  return request<YearlyCaseStat[]>('/api/dashboard/cases-by-year');
}

export interface TopDiseaseGroup {
  disease_group: string;
  case_count: number;
}

export function getTopDiseaseGroups(dataType = 'predict_current', limit = 10): Promise<TopDiseaseGroup[]> {
  return request<TopDiseaseGroup[]>(
    `/api/dashboard/top-disease-groups?data_type=${encodeURIComponent(dataType)}&limit=${limit}`,
  );
}

// ===== Import =====

async function uploadFile<T>(path: string, file: File): Promise<T> {
  const token = getToken();
  const fd = new FormData();
  fd.append('file', file);

  const res = await fetch(path, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: fd,
  });

  if (!res.ok) {
    let detail = 'Upload thất bại';
    try {
      const data = await res.json();
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

export function importPatientData(file: File) {
  return uploadFile<{ message: string; result: unknown }>('/api/import/predict-current', file);
}

export function importDiseaseCodes(file: File) {
  return uploadFile<{ message: string; total_codes: number; file: string }>('/api/import/disease-codes', file);
}

export interface ParentGuidePreview {
  sheet: string;
  columns: string[];
  required_columns: string[];
  missing_columns: string[];
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_groups_removed: number;
  sample_rows: Array<Record<string, string>>;
}

export interface ParentGuideStatus {
  has_parent_guide: boolean;
  total_rows: number;
  uploaded_file: string | null;
}

export interface ParentGuideListResponse {
  total: number;
  limit: number;
  offset: number;
  rows: DiseaseKnowledgeRow[];
}

export function previewParentGuide(file: File) {
  return uploadFile<ParentGuidePreview>('/api/import/parent-guide/preview', file);
}

export function importParentGuide(file: File) {
  return uploadFile<{ message: string; result: { total_rows: number; saved_rows: number; invalid_rows: number } }>(
    '/api/import/parent-guide',
    file,
  );
}

export function getParentGuideStatus(): Promise<ParentGuideStatus> {
  return request<ParentGuideStatus>('/api/import/parent-guide/status');
}

export function listParentGuide(params: {
  search?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ParentGuideListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set('search', params.search);
  qs.set('limit', String(params.limit ?? 50));
  qs.set('offset', String(params.offset ?? 0));
  return request<ParentGuideListResponse>(`/api/import/parent-guide?${qs.toString()}`);
}

export interface DiseaseCodesStatus {
  has_disease_codes: boolean;
  total_codes: number;
  distinct_groups: number;
  uploaded_file: string | null;
}

export interface DiseaseCodeRow {
  id: number;
  icd_code: string;
  disease_name: string | null;
  group_id: string | null;
  group_name: string | null;
  report_group_code: string | null;
  english_name: string | null;
  missing_group: boolean;
}

export interface DiseaseCodesListResponse {
  total: number;
  limit: number;
  offset: number;
  missing_group_total: number;
  rows: DiseaseCodeRow[];
}

export function getDiseaseCodesStatus(): Promise<DiseaseCodesStatus> {
  return request<DiseaseCodesStatus>('/api/import/disease-codes/status');
}

export function listDiseaseCodes(params: {
  search?: string;
  limit?: number;
  offset?: number;
  onlyMissingGroup?: boolean;
} = {}): Promise<DiseaseCodesListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set('search', params.search);
  qs.set('limit', String(params.limit ?? 50));
  qs.set('offset', String(params.offset ?? 0));
  if (params.onlyMissingGroup) qs.set('only_missing_group', 'true');
  return request<DiseaseCodesListResponse>(`/api/import/disease-codes?${qs.toString()}`);
}

// ===== Forecast =====

export function runForecast(lastCompletedPeriod = 'auto', horizon = 1) {
  const qs = new URLSearchParams({
    last_completed_period: lastCompletedPeriod,
    forecast_horizon: String(horizon),
  });
  return request<{ message: string; result: unknown }>(`/api/forecast/run?${qs.toString()}`, {
    method: 'POST',
  });
}

export function runWeatherForecast(lastCompletedPeriod = 'auto', horizon = 1) {
  const qs = new URLSearchParams({
    last_completed_period: lastCompletedPeriod,
    forecast_horizon: String(horizon),
  });
  return request<{
    message: string;
    result: {
      forecast_periods: string[];
      rows: number;
      model: string;
      metrics?: { mae: number; rmse: number; valid_periods: string[] };
    };
  }>(`/api/forecast/run-weather?${qs.toString()}`, {
    method: 'POST',
  });
}

export interface ForecastGroupSummary {
  forecast_period: string;
  disease_group: string;
  previous_cases: number;
  predicted_cases: number;
  change_percent: number | null;
  trend: string;
  risk_level: string;
}

export function getForecastGroupSummary(forecastPeriod?: string): Promise<ForecastGroupSummary[]> {
  const qs = forecastPeriod ? `?forecast_period=${encodeURIComponent(forecastPeriod)}` : '';
  return request<ForecastGroupSummary[]>(`/api/forecast/group-summary${qs}`);
}

export interface ForecastResult {
  id: number;
  forecast_period: string;
  disease_group: string;
  age_group: string;
  previous_cases: number;
  predicted_cases: number;
  change_percent: number | null;
  trend: string;
  risk_level: string;
}

export function getForecastResults(forecastPeriod?: string): Promise<ForecastResult[]> {
  const qs = forecastPeriod ? `?forecast_period=${encodeURIComponent(forecastPeriod)}` : '';
  return request<ForecastResult[]>(`/api/forecast/results${qs}`);
}

export interface DiseaseKnowledgeRow {
  id: number;
  disease_group: string;
  title: string;
  description?: string | null;
  symptoms?: string | null;
  warning_signs?: string | null;
  prevention?: string | null;
  source?: string | null;
}

export function getPublicDiseaseKnowledge(): Promise<DiseaseKnowledgeRow[]> {
  return request<DiseaseKnowledgeRow[]>('/api/public/disease-knowledge', { skipAuth: true });
}

// ===== Admin =====

export interface AdminUser {
  id: number;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  permissions: string[];
  birth_date?: string | null;
  gender?: string | null;
  position?: string | null;
}

export interface CreateUserPayload {
  username: string;
  password: string;
  full_name?: string;
  role?: string;
  position?: string;
  permissions?: string[];
}

export interface PermissionDef {
  code: string;
  label: string;
  group: string;
  description?: string;
}

export function listUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>('/api/admin/users');
}

export function createUser(payload: CreateUserPayload): Promise<AdminUser> {
  return request<AdminUser>('/api/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function listRoles(): Promise<{ roles: string[] }> {
  return request<{ roles: string[] }>('/api/admin/roles');
}

export function listPermissions(): Promise<{ permissions: PermissionDef[]; default_staff_permissions: string[] }> {
  return request<{ permissions: PermissionDef[]; default_staff_permissions: string[] }>('/api/admin/permissions');
}

export function updateUserRole(userId: number, role: string) {
  return request<AdminUser>(`/api/admin/users/${userId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });
}

export function updateUserActive(userId: number, isActive: boolean) {
  return request<AdminUser>(`/api/admin/users/${userId}/active`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active: isActive }),
  });
}

export function updateUserPermissions(userId: number, permissions: string[]) {
  return request<AdminUser>(`/api/admin/users/${userId}/permissions`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ permissions }),
  });
}

export function resetUserPassword(userId: number, password: string) {
  return request<{ username: string; message: string }>(`/api/admin/users/${userId}/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
}

export function deleteUser(userId: number) {
  return request<{ message: string }>(`/api/admin/users/${userId}`, { method: 'DELETE' });
}

export function bulkCreateUsers(payload: {
  username_prefix: string;
  count: number;
  password: string;
  role: string;
  permissions: string[];
  full_name_prefix?: string;
  position?: string;
}) {
  return request<{ created: Array<{ username: string; password: string; role: string }> }>('/api/admin/users/bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ===== Reports =====

export interface AgeMonthsReport {
  data_type: string;
  period_from: string | null;
  period_to: string | null;
  buckets: Array<{
    age_bucket: string;
    total: number;
    rows: Array<{ disease_group: string; case_count: number }>;
  }>;
}

export function getReportByAgeMonths(params: {
  dataType?: string;
  periodFrom?: string;
  periodTo?: string;
} = {}): Promise<AgeMonthsReport> {
  const qs = new URLSearchParams();
  if (params.dataType) qs.set('data_type', params.dataType);
  if (params.periodFrom) qs.set('period_from', params.periodFrom);
  if (params.periodTo) qs.set('period_to', params.periodTo);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request<AgeMonthsReport>(`/api/reports/by-age-months${suffix}`);
}

export interface MonthYearReport {
  data_type: string;
  rows: Array<{
    year: number;
    total: number;
    months: Array<{ month: number; case_count: number }>;
  }>;
}

export function getReportByMonthYear(dataType = 'predict_current'): Promise<MonthYearReport> {
  return request<MonthYearReport>(
    `/api/reports/by-month-year?data_type=${encodeURIComponent(dataType)}`,
  );
}

export function getDiseaseBilingual(): Promise<Record<string, string>> {
  return request<Record<string, string>>('/api/reports/disease-bilingual');
}

// ===== Weather AI risk prediction =====

export interface WeatherAIStatus {
  ready: boolean;
  model_path?: string;
  model_type?: string;
  description?: string;
  age_groups?: string[];
  genders?: string[];
  disease_groups?: number;
  training_summary?: Record<string, unknown>;
  training_weather_scope?: string;
  runtime_weather_note?: string;
  predicted_cases_unit?: string;
  message?: string;
}

export interface WeatherAIDiseaseCatalogItem {
  disease_group_id: string;
  report_group_code?: string | null;
  disease_group_name: string;
}

export interface WeatherAIOptions {
  age_groups: string[];
  genders: string[];
  disease_catalog: WeatherAIDiseaseCatalogItem[];
}

export interface ManualWeatherPayload {
  temperature?: number;
  humidity?: number;
  rain?: number;
  weather_code?: number;
  wind_speed?: number;
  wind_gusts?: number;
}

export interface WeatherAIRiskItem {
  disease_group_id: string;
  report_group_code?: string | null;
  disease_group_name: string;
  probability: number;
  predicted_cases: number;
  predicted_cases_unit?: string;
  risk_score: number;
  risk_level: string;
}

export interface WeatherAIPredictResponse {
  message: string;
  input: {
    age_group: string;
    gender: string;
    top_k: number;
  };
  weather: {
    meta?: Record<string, unknown>;
    features: Record<string, number>;
    month: number;
    season: string;
  };
  top_risks: WeatherAIRiskItem[];
  model?: {
    model_type?: string;
    training_summary?: Record<string, unknown>;
    training_weather_scope?: string;
    runtime_weather_note?: string;
    predicted_cases_unit?: string;
  };
}

export function getWeatherAIStatus(): Promise<WeatherAIStatus> {
  return request<WeatherAIStatus>('/api/weather-ai/status');
}

export function getWeatherAIOptions(): Promise<WeatherAIOptions> {
  return request<WeatherAIOptions>('/api/weather-ai/options');
}

export function predictWeatherAIRisk(payload: {
  age_group: string;
  gender: string;
  top_k?: number;
  latitude?: number;
  longitude?: number;
  timezone?: string;
  weather?: ManualWeatherPayload;
}): Promise<WeatherAIPredictResponse> {
  return request<WeatherAIPredictResponse>('/api/weather-ai/predict-risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function getPublicWeatherAIOptions(): Promise<WeatherAIOptions> {
  return request<WeatherAIOptions>('/api/public/weather-options', { skipAuth: true });
}

export function predictPublicParentRisk(payload: {
  age_group: string;
  gender: string;
  top_k?: number;
  latitude?: number;
  longitude?: number;
  timezone?: string;
  weather?: ManualWeatherPayload;
}): Promise<WeatherAIPredictResponse> {
  return request<WeatherAIPredictResponse>('/api/public/parent-risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

// ===== Dashboard advanced filters / analysis =====

export interface DashboardPeriodOption {
  period: string;
  year: number;
  month: number;
  season: string;
}

export interface DashboardDiseaseGroupOption {
  disease_group: string;
  total_cases: number;
}

export interface TopDiseaseGroupByMonth {
  period: string;
  disease_group: string;
  case_count: number;
}

export interface DiseasePercentageByMonth {
  period: string;
  disease_group: string;
  case_count: number;
  total_cases_in_month: number;
  percentage: number;
}

export interface SeasonalSummaryRow {
  season: string;
  disease_group: string;
  case_count: number;
}

export interface MonthlyComparisonRow {
  period: string;
  previous_period: string;
  disease_group: string;
  previous_cases: number;
  current_cases: number;
  change_percent: number | null;
  trend: string;
}

export interface CasesByAgeRangeResult {
  period: string;
  min_month_age: number | null;
  max_month_age: number | null;
  total_cases: number;
}

export interface DiseaseByAgeRangeRow {
  period: string;
  min_month_age: number | null;
  max_month_age: number | null;
  disease_group: string;
  case_count: number;
  period_distribution?: Array<{ period: string; case_count: number }>;
  peak_period?: string | null;
  peak_period_cases?: number;
  first_period?: string | null;
  latest_period?: string | null;
}

export interface CasesByGenderRow {
  period: string;
  gender: string;
  case_count: number;
  percentage: number;
}

export interface DiseaseTrendRow {
  period: string;
  disease_group: string;
  case_count: number;
}

export interface YearOverYearRow {
  year: number;
  month: number;
  disease_group: string;
  case_count: number;
}

export interface SeasonalPeakRow {
  disease_group: string;
  peak_month: number;
  avg_cases: number;
  season: string;
}

export interface DiseaseByGenderRow {
  disease_group: string;
  male_cases: number;
  female_cases: number;
  other_cases: number;
  total_cases: number;
  male_percent: number;
  female_percent: number;
}

export interface DiseaseSeasonComparisonRow {
  disease_group: string;
  dry_season_cases: number;
  rainy_season_cases: number;
  total_cases: number;
  dominant_season: string;
  dry_percent: number;
  rainy_percent: number;
}

export interface SummaryCardResponse {
  period: string;
  previous_period: string;
  total_cases: number;
  previous_month_cases: number;
  change_percent: number | null;
  trend: string;
  season: string;
  top_3_diseases: Array<{ disease_group: string; case_count: number }>;
}

export function getDashboardPeriods(): Promise<DashboardPeriodOption[]> {
  return request<DashboardPeriodOption[]>('/api/dashboard/periods');
}

export function getDashboardDiseaseGroups(): Promise<DashboardDiseaseGroupOption[]> {
  return request<DashboardDiseaseGroupOption[]>('/api/dashboard/disease-groups');
}

export function getSummaryCard(period: string): Promise<SummaryCardResponse> {
  return request<SummaryCardResponse>(`/api/dashboard/summary-card?period=${encodeURIComponent(period)}`);
}

export function getTopDiseaseGroupsByMonth(period: string, limit = 10): Promise<TopDiseaseGroupByMonth[]> {
  return request<TopDiseaseGroupByMonth[]>(
    `/api/dashboard/top-disease-groups-by-month?period=${encodeURIComponent(period)}&limit=${limit}`,
  );
}

export function getDiseasePercentageByMonth(period: string, limit = 10): Promise<DiseasePercentageByMonth[]> {
  return request<DiseasePercentageByMonth[]>(
    `/api/dashboard/disease-percentage-by-month?period=${encodeURIComponent(period)}&limit=${limit}`,
  );
}

export function getSeasonalSummary(season?: string, limit = 20): Promise<SeasonalSummaryRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (season) qs.set('season', season);
  return request<SeasonalSummaryRow[]>(`/api/dashboard/seasonal-summary?${qs.toString()}`);
}

export function getMonthlyComparison(period: string, limit = 20): Promise<MonthlyComparisonRow[]> {
  return request<MonthlyComparisonRow[]>(
    `/api/dashboard/monthly-comparison?period=${encodeURIComponent(period)}&limit=${limit}`,
  );
}

export function getCasesByAgeRange(params: {
  period?: string;
  minMonthAge?: number;
  maxMonthAge?: number;
} = {}): Promise<CasesByAgeRangeResult> {
  const qs = new URLSearchParams();
  if (params.period) qs.set('period', params.period);
  if (params.minMonthAge !== undefined) qs.set('min_month_age', String(params.minMonthAge));
  if (params.maxMonthAge !== undefined) qs.set('max_month_age', String(params.maxMonthAge));
  return request<CasesByAgeRangeResult>(`/api/dashboard/cases-by-age-range?${qs.toString()}`);
}

export function getDiseaseByAgeRange(params: {
  period?: string;
  minMonthAge?: number;
  maxMonthAge?: number;
  limit?: number;
} = {}): Promise<DiseaseByAgeRangeRow[]> {
  const qs = new URLSearchParams();
  if (params.period) qs.set('period', params.period);
  if (params.minMonthAge !== undefined) qs.set('min_month_age', String(params.minMonthAge));
  if (params.maxMonthAge !== undefined) qs.set('max_month_age', String(params.maxMonthAge));
  qs.set('limit', String(params.limit ?? 20));
  return request<DiseaseByAgeRangeRow[]>(`/api/dashboard/disease-by-age-range?${qs.toString()}`);
}

export function getCasesByGender(params: { period?: string; year?: number } = {}): Promise<CasesByGenderRow[]> {
  const qs = new URLSearchParams();
  if (params.period) qs.set('period', params.period);
  if (params.year !== undefined) qs.set('year', String(params.year));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request<CasesByGenderRow[]>(`/api/dashboard/cases-by-gender${suffix}`);
}

export function getDiseaseTrend(params: {
  diseaseGroup: string;
  startPeriod?: string;
  endPeriod?: string;
}): Promise<DiseaseTrendRow[]> {
  const qs = new URLSearchParams({ disease_group: params.diseaseGroup });
  if (params.startPeriod) qs.set('start_period', params.startPeriod);
  if (params.endPeriod) qs.set('end_period', params.endPeriod);
  return request<DiseaseTrendRow[]>(`/api/dashboard/disease-trend?${qs.toString()}`);
}

export function getYearOverYear(month: number, diseaseGroup?: string): Promise<YearOverYearRow[]> {
  const qs = new URLSearchParams({ month: String(month) });
  if (diseaseGroup) qs.set('disease_group', diseaseGroup);
  return request<YearOverYearRow[]>(`/api/dashboard/year-over-year?${qs.toString()}`);
}

export function getSeasonalPeak(limit = 10): Promise<SeasonalPeakRow[]> {
  return request<SeasonalPeakRow[]>(`/api/dashboard/seasonal-peak?limit=${limit}`);
}

export function getDiseaseByGender(params: {
  period?: string;
  year?: number;
  diseaseGroup?: string;
  limit?: number;
} = {}): Promise<DiseaseByGenderRow[]> {
  const qs = new URLSearchParams({ limit: String(params.limit ?? 10) });
  if (params.period) qs.set('period', params.period);
  if (params.year !== undefined) qs.set('year', String(params.year));
  if (params.diseaseGroup) qs.set('disease_group', params.diseaseGroup);
  return request<DiseaseByGenderRow[]>(`/api/dashboard/disease-by-gender?${qs.toString()}`);
}

export function getDiseaseSeasonComparison(diseaseGroup?: string, limit = 10): Promise<DiseaseSeasonComparisonRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (diseaseGroup) qs.set('disease_group', diseaseGroup);
  return request<DiseaseSeasonComparisonRow[]>(`/api/dashboard/disease-season-comparison?${qs.toString()}`);
}

// ===== Province / city area statistics =====

export interface AreaOption {
  code: string;
  name: string;
  province_code?: string | null;
  district_code?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  is_active: boolean;
}

export interface AreaCaseSummary {
  area_code: string | null;
  area_name: string;
  level: string;
  case_count: number;
  disease_groups: number;
}

export interface AreaDiseaseSummary {
  disease_group: string;
  case_count: number;
}

export interface AreaLocalRisk {
  disease_group: string;
  recent_cases: number;
  risk_level: string;
  forecast_risk_level?: string | null;
  period_from?: string | null;
  period_to?: string | null;
}

export interface AreaRecommendations {
  area: {
    province: AreaOption | null;
    district: AreaOption | null;
    ward: AreaOption | null;
  };
  top_risks: AreaLocalRisk[];
  recommendations: string[];
}

export function listAreaProvinces(): Promise<AreaOption[]> {
  return request<AreaOption[]>('/api/areas/provinces', { skipAuth: true });
}

export function getAreaCaseSummary(params: {
  provinceCode?: string;
  limit?: number;
} = {}): Promise<AreaCaseSummary[]> {
  const qs = new URLSearchParams({ level: 'province', limit: String(params.limit ?? 20) });
  if (params.provinceCode) qs.set('province_code', params.provinceCode);
  return request<AreaCaseSummary[]>(`/api/areas/case-summary?${qs.toString()}`);
}

export function getAreaDiseaseSummary(params: {
  provinceCode?: string;
  limit?: number;
} = {}): Promise<AreaDiseaseSummary[]> {
  const qs = new URLSearchParams({ limit: String(params.limit ?? 20) });
  if (params.provinceCode) qs.set('province_code', params.provinceCode);
  return request<AreaDiseaseSummary[]>(`/api/areas/disease-summary?${qs.toString()}`);
}

export function getAreaLocalRisks(params: {
  provinceCode?: string;
  limit?: number;
} = {}): Promise<AreaLocalRisk[]> {
  const qs = new URLSearchParams({ limit: String(params.limit ?? 10) });
  if (params.provinceCode) qs.set('province_code', params.provinceCode);
  return request<AreaLocalRisk[]>(`/api/areas/local-risks?${qs.toString()}`, { skipAuth: true });
}

export function getAreaRecommendations(params: {
  provinceCode?: string;
} = {}): Promise<AreaRecommendations> {
  const qs = new URLSearchParams();
  if (params.provinceCode) qs.set('province_code', params.provinceCode);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request<AreaRecommendations>(`/api/areas/recommendations${suffix}`, { skipAuth: true });
}

export function syncDefaultAreas(): Promise<{ message: string; inserted: Record<string, number> }> {
  return request<{ message: string; inserted: Record<string, number> }>('/api/areas/sync-defaults', {
    method: 'POST',
  });
}
