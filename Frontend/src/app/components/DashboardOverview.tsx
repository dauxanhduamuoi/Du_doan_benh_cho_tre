import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Users,
  Calendar,
  Activity,
  Layers,
  PlayCircle,
  RefreshCcw,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  X,
  Search,
  ChevronRight,
} from 'lucide-react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import * as api from '@/lib/api';
import { addNotification } from '@/lib/notifications';
import { useT } from '@/lib/i18n';
import DiseaseLabelCell from './common/DiseaseLabelCell';
import { ensureBilingualMap, splitDiseaseLabel, fuzzyMatch } from '@/lib/disease';
import { sortAgeGroups } from '@/lib/age';

type DataType = 'train_history' | 'predict_current';

const PIE_COLORS = [
  '#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2',
  '#be123c', '#7c3aed', '#ca8a04', '#0f766e', '#4338ca', '#64748b',
];

interface Toast {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

const RISK_COLORS: Record<string, string> = {
  Cao: 'bg-red-100 text-red-700 border-red-200',
  'Trung bình': 'bg-amber-100 text-amber-700 border-amber-200',
  'Thấp': 'bg-emerald-100 text-emerald-700 border-emerald-200',
};

function riskLabel(level: string, t: (k: string) => string): string {
  if (level === 'Cao') return t('common.high');
  if (level === 'Trung bình') return t('common.medium');
  if (level === 'Thấp') return t('common.low');
  return level;
}

/**
 * Legend item dạng 2 dòng: VN (đậm) + EN (italic) cho các chart Recharts.
 * `payload` mà Recharts truyền có shape: [{ value, color, dataKey, payload, ... }].
 */
function BilingualLegend({
  payload,
  bilingualMap,
}: {
  payload?: Array<{ value: string; color: string }>;
  bilingualMap: Record<string, string>;
}) {
  if (!payload || payload.length === 0) return null;
  return (
    <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1.5 mt-2 text-xs">
      {payload.map((entry, i) => {
        const lbl = splitDiseaseLabel(entry.value, bilingualMap);
        return (
          <li key={`${entry.value}-${i}`} className="flex items-start gap-1.5 max-w-[260px]">
            <span
              className="inline-block w-3 h-3 mt-0.5 rounded-sm shrink-0"
              style={{ backgroundColor: entry.color }}
            />
            <span className="leading-tight">
              <span className="font-medium" style={{ color: entry.color }}>
                {lbl.vi}
              </span>
              {lbl.en && (
                <>
                  <br />
                  <span className="italic text-slate-500">{lbl.en}</span>
                </>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default function DashboardOverview() {
  const t = useT();
  // Dashboard phân tích dữ liệu người dùng import hiện tại (predict_current).
  // train_history chỉ dùng cho model AI/forecast, không dùng để vẽ dashboard phân tích.
  const dataType: DataType = 'predict_current';

  const [overview, setOverview] = useState<api.OverviewResponse | null>(null);
  const [monthly, setMonthly] = useState<api.MonthlyStat[]>([]);
  const [yearlyCases, setYearlyCases] = useState<api.YearlyCaseStat[]>([]);
  const [topGroups, setTopGroups] = useState<api.TopDiseaseGroup[]>([]);
  const [topLimit, setTopLimit] = useState(8);
  const [forecast, setForecast] = useState<api.ForecastGroupSummary[]>([]);
  // Chi tiết theo (period × disease × age) — load song song để bảng Forecast
  // có thể expand từng nhóm bệnh xem breakdown theo nhóm tuổi.
  const [forecastDetails, setForecastDetails] = useState<api.ForecastResult[]>([]);
  const [expandedForecastKeys, setExpandedForecastKeys] = useState<Set<string>>(new Set());

  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const [bilingualMap, setBilingualMap] = useState<Record<string, string>>({});

  useEffect(() => {
    ensureBilingualMap().then(setBilingualMap).catch(() => undefined);
  }, []);

  const pushToast = useCallback((type: Toast['type'], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, ms, yc, tg, fc, fd] = await Promise.all([
        api.getOverview(dataType),
        api.getMonthlyStatistics(dataType),
        api.getCasesByYear(),
        api.getTopDiseaseGroups(dataType, topLimit),
        api.getForecastGroupSummary().catch(() => [] as api.ForecastGroupSummary[]),
        api.getForecastResults().catch(() => [] as api.ForecastResult[]),
      ]);
      setOverview(ov);
      setMonthly(ms);
      setYearlyCases(yc);
      setTopGroups(tg);
      setForecast(fc);
      setForecastDetails(fd);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dataType, topLimit]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const monthlyChartData = useMemo(() => {
    const byPeriod = new Map<string, number>();
    for (const row of monthly) {
      byPeriod.set(row.period, (byPeriod.get(row.period) ?? 0) + row.case_count);
    }
    return Array.from(byPeriod.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, cases]) => ({ period, cases }));
  }, [monthly]);

  const yearlyChartData = useMemo(
    () =>
      yearlyCases.map((row) => ({
        year: String(row.year),
        cases: row.case_count,
        monthCount: row.month_count,
        missingMonths: row.missing_months,
        isCompleteYear: row.is_complete_year,
      })),
    [yearlyCases],
  );

  const incompleteYears = useMemo(
    () => yearlyCases.filter((row) => !row.is_complete_year),
    [yearlyCases],
  );

  const stackedTopChartData = useMemo(() => {
    if (monthly.length === 0) return { data: [] as Array<Record<string, number | string>>, groups: [] as string[] };
    const topNames = topGroups.slice(0, topLimit).map((g) => g.disease_group);
    const topSet = new Set(topNames);

    const periods = Array.from(new Set(monthly.map((m) => m.period))).sort();

    const data = periods.map((period) => {
      const row: Record<string, number | string> = { period };
      for (const name of topNames) row[name] = 0;
      return row;
    });

    const rowByPeriod = new Map<string, Record<string, number | string>>();
    data.forEach((r) => rowByPeriod.set(r.period as string, r));

    for (const m of monthly) {
      if (!topSet.has(m.disease_group)) continue;
      const row = rowByPeriod.get(m.period);
      if (!row) continue;
      row[m.disease_group] = (row[m.disease_group] as number) + m.case_count;
    }

    return { data, groups: topNames };
  }, [monthly, topGroups, topLimit]);

  const pieData = useMemo(
    () =>
      topGroups.map((g, i) => {
        const lbl = splitDiseaseLabel(g.disease_group, bilingualMap);
        return {
          name: g.disease_group,
          vi: lbl.vi || g.disease_group,
          en: lbl.en,
          value: g.case_count,
          color: PIE_COLORS[i % PIE_COLORS.length],
        };
      }),
    [topGroups, bilingualMap],
  );

  const handleRunForecast = async () => {
    setBusyAction('forecast');
    try {
      await api.runForecast('auto', 1);
      const [fc, fd] = await Promise.all([
        api.getForecastGroupSummary(),
        api.getForecastResults().catch(() => [] as api.ForecastResult[]),
      ]);
      setForecast(fc);
      setForecastDetails(fd);
      const high = fc.filter((r) => r.risk_level === 'Cao').length;
      pushToast('success', t('dashboard.forecastDone'));
      addNotification({
        type: 'forecast',
        severity: high > 0 ? 'warning' : 'info',
        title: t('dashboard.forecastDone'),
        description: `${t('forecast.highRisk')}: ${high}`,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      pushToast('error', msg);
      addNotification({
        type: 'forecast',
        severity: 'critical',
        title: t('dashboard.forecastFailed'),
        description: msg,
      });
    } finally {
      setBusyAction(null);
    }
  };

  const [forecastSearch, setForecastSearch] = useState('');
  const [forecastDebouncedSearch, setForecastDebouncedSearch] = useState('');
  const [forecastPage, setForecastPage] = useState(1);
  const [forecastPageSize, setForecastPageSize] = useState(20);

  useEffect(() => {
    const id = setTimeout(() => setForecastDebouncedSearch(forecastSearch.trim()), 200);
    return () => clearTimeout(id);
  }, [forecastSearch]);

  // Reset về trang 1 khi search/page-size thay đổi hoặc data load mới.
  useEffect(() => {
    setForecastPage(1);
  }, [forecastDebouncedSearch, forecast.length, forecastPageSize]);

  const filteredForecast = useMemo(() => {
    if (!forecastDebouncedSearch) return forecast;
    return forecast.filter((row) => {
      const lbl = splitDiseaseLabel(row.disease_group, bilingualMap);
      const haystack = `${row.forecast_period} ${lbl.vi} ${lbl.en ?? ''} ${row.trend} ${row.risk_level}`;
      return fuzzyMatch(haystack, forecastDebouncedSearch);
    });
  }, [forecast, forecastDebouncedSearch, bilingualMap]);

  const forecastTotalPages = Math.max(1, Math.ceil(filteredForecast.length / forecastPageSize));
  const forecastPageRows = useMemo(() => {
    const start = (forecastPage - 1) * forecastPageSize;
    return filteredForecast.slice(start, start + forecastPageSize);
  }, [filteredForecast, forecastPage, forecastPageSize]);

  const statsCards = useMemo(
    () => [
      {
        title: t('dashboard.totalRecords'),
        value: overview?.total_records ?? 0,
        icon: Users,
        iconBg: 'bg-blue-100',
        iconColor: 'text-blue-600',
        borderColor: 'border-l-blue-500',
      },
      {
        title: t('dashboard.totalPeriods'),
        value: overview?.total_periods ?? 0,
        icon: Calendar,
        iconBg: 'bg-emerald-100',
        iconColor: 'text-emerald-600',
        borderColor: 'border-l-emerald-500',
      },
      {
        title: t('dashboard.totalGroups'),
        value: overview?.total_disease_groups ?? 0,
        icon: Layers,
        iconBg: 'bg-amber-100',
        iconColor: 'text-amber-600',
        borderColor: 'border-l-amber-500',
      },
      {
        title: t('dashboard.forecastRuns'),
        value: forecast.length,
        icon: Activity,
        iconBg: 'bg-purple-100',
        iconColor: 'text-purple-600',
        borderColor: 'border-l-purple-500',
      },
    ],
    [forecast.length, overview, t],
  );

  return (
    <div className="space-y-6 relative">
      {/* Toasts */}
      <div className="fixed top-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-start gap-2 px-4 py-3 rounded-xl shadow-lg border min-w-[280px] max-w-sm ${
              toast.type === 'success'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : toast.type === 'error'
                ? 'bg-red-50 border-red-200 text-red-800'
                : 'bg-slate-50 border-slate-200 text-slate-700'
            }`}
          >
            {toast.type === 'success' ? (
              <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
            ) : toast.type === 'error' ? (
              <AlertTriangle size={18} className="shrink-0 mt-0.5" />
            ) : null}
            <span className="text-sm flex-1 break-words">{toast.message}</span>
            <button
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== toast.id))}
              className="text-slate-400 hover:text-slate-600"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Action bar */}
      <div className="bg-white rounded-xl p-4 border border-slate-200 shadow-sm flex flex-wrap items-center gap-3">
        <button
          onClick={handleRunForecast}
          disabled={busyAction === 'forecast'}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
        >
          {busyAction === 'forecast' ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
          {t('dashboard.runForecast')}
        </button>

        <label className="inline-flex items-center gap-2 text-sm text-slate-600 ml-auto">
          {t('dashboard.topGroups')}
          <select
            value={topLimit}
            onChange={(e) => setTopLimit(Number(e.target.value))}
            className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            title={t('dashboard.topGroupsHint')}
          >
            {[5, 6, 8, 10, 12].map((n) => (
              <option key={n} value={n}>Top {n}</option>
            ))}
          </select>
        </label>

        <button
          onClick={loadAll}
          disabled={loading}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
          {t('common.refresh')}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm">
          {t('dashboard.loadError')}: {error}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        {statsCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.title}
              className={`bg-white rounded-xl p-5 border border-slate-200 border-l-4 ${stat.borderColor} shadow-sm hover:shadow-md transition-shadow duration-200`}
            >
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <p className="text-sm text-slate-500">{stat.title}</p>
                  <p className="text-3xl font-bold text-slate-800">
                    {loading && overview === null ? '—' : stat.value.toLocaleString()}
                  </p>
                  <p className="text-xs text-slate-400 pt-1">
                    {t('settings.data.current')}
                  </p>
                </div>
                <div className={`p-3 rounded-xl ${stat.iconBg}`}>
                  <Icon className={stat.iconColor} size={22} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-800">{t('dashboard.yearlyCasesTitle')}</h3>
            <p className="text-xs text-slate-500 mt-1">
              {t('dashboard.yearlyCasesDesc')}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 ring-1 ring-blue-100">
              {yearlyChartData.length} {t('dashboard.yearUnit')}
            </span>
            {incompleteYears.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 ring-1 ring-amber-100">
                <AlertTriangle size={12} />
                {incompleteYears.length} {t('dashboard.incompleteYearCount')}
              </span>
            )}
          </div>
        </div>
        {yearlyChartData.length === 0 ? (
          <EmptyChart loading={loading} label={t('dashboard.noData')} t={t} />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={yearlyChartData} margin={{ top: 10, right: 20, left: 8, bottom: 18 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{ borderRadius: '0.75rem', border: '1px solid #e2e8f0' }}
                  formatter={(value: number) => [
                    `${value.toLocaleString()} ${t('dashboard.caseUnit')}`,
                    t('dashboard.totalCases'),
                  ]}
                  labelFormatter={(label, payload) => {
                    const row = payload?.[0]?.payload as
                      | { monthCount?: number; isCompleteYear?: boolean; missingMonths?: number[] }
                      | undefined;
                    if (!row) return `${t('dashboard.yearLabel')} ${label}`;
                    const status = row.isCompleteYear
                      ? t('dashboard.fullYearStatus')
                      : `${t('dashboard.hasMonthsStatus')} ${row.monthCount ?? 0}/12 ${t('reports.col.month').toLowerCase()}`;
                    return `${t('dashboard.yearLabel')} ${label} - ${status}`;
                  }}
                />
                <Bar dataKey="cases" name={t('dashboard.totalCases')} radius={[7, 7, 0, 0]}>
                  {yearlyChartData.map((entry) => (
                    <Cell
                      key={entry.year}
                      fill={entry.isCompleteYear ? '#0f766e' : '#f59e0b'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {incompleteYears.length > 0 && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <div className="mb-2 flex items-center gap-2 font-semibold">
                  <AlertTriangle size={16} />
                  {t('dashboard.incompleteYearsTitle')}
                </div>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {incompleteYears.map((row) => (
                    <div key={row.year} className="rounded-lg bg-white/70 px-3 py-2 ring-1 ring-amber-100">
                      <div className="font-semibold">
                        {t('dashboard.yearLabel')} {row.year}: {t('dashboard.hasMonthsStatus')} {row.month_count}/12{' '}
                        {t('reports.col.month').toLowerCase()}
                      </div>
                      <div className="mt-1 text-xs text-amber-700">
                        {t('dashboard.missingMonths')}: {row.missing_months.length > 0
                          ? row.missing_months.map((m) => `T${m}`).join(', ')
                          : t('dashboard.unknown')}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-800 mb-4">{t('dashboard.monthlyCases')}</h3>
          {monthlyChartData.length === 0 ? (
            <EmptyChart loading={loading} label={t('dashboard.noData')} t={t} />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={monthlyChartData} margin={{ bottom: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={{ borderRadius: '0.75rem', border: '1px solid #e2e8f0' }} />
                <Legend
                  verticalAlign="bottom"
                  content={(props) => (
                    <BilingualLegend
                      payload={props.payload as unknown as Array<{ value: string; color: string }>}
                      bilingualMap={bilingualMap}
                    />
                  )}
                />
                <Line type="monotone" dataKey="cases" name={t('dashboard.cases')} stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-800">{t('dashboard.topGroups')}</h3>
              <p className="text-xs text-slate-500 mt-1">
                Lấy trực tiếp từ API /api/dashboard/top-disease-groups theo lựa chọn Top {topLimit}, không fix cứng ở frontend.
              </p>
            </div>
          </div>
          {pieData.length === 0 ? (
            <EmptyChart loading={loading} label={t('dashboard.noGroupData')} t={t} />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-center">
              {/* Pie không có label ngoài — dùng legend bên cạnh để tránh chèn chữ */}
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={(props) => {
                      const p = props as unknown as { percent: number };
                      // Chỉ hiện % khi miếng đủ to, không kẹp tên bệnh để khỏi chồng.
                      if (p.percent < 0.06) return '';
                      return `${(p.percent * 100).toFixed(0)}%`;
                    }}
                    outerRadius={95}
                    innerRadius={55}
                    dataKey="value"
                    paddingAngle={2}
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ borderRadius: '0.75rem', border: '1px solid #e2e8f0' }}
                    formatter={(value: number, _name, item) => {
                      const p = (item as unknown as { payload: { vi: string; en: string | null } }).payload;
                      return [`${value} ${t('col.cases').toLowerCase()}`, p.en ? `${p.vi}\n${p.en}` : p.vi];
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>

              {/* Legend bên phải: VN dòng trên, EN dòng dưới + số ca */}
              <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
                {pieData.map((entry, idx) => {
                  const total = pieData.reduce((a, b) => a + b.value, 0) || 1;
                  const pct = ((entry.value / total) * 100).toFixed(0);
                  return (
                    <div key={idx} className="flex items-start gap-2 text-xs">
                      <span
                        className="inline-block w-3 h-3 rounded-sm mt-0.5 shrink-0"
                        style={{ backgroundColor: entry.color }}
                      />
                      <div className="min-w-0 flex-1 leading-tight">
                        <div className="font-medium" style={{ color: entry.color }}>
                          {entry.vi} <span className="text-slate-500">{pct}%</span>
                        </div>
                        {entry.en && <div className="italic text-slate-500">{entry.en}</div>}
                      </div>
                      <span className="text-[11px] text-slate-500 tabular-nums shrink-0">
                        {entry.value.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-slate-800">{t('dashboard.topByPeriod')}</h3>
          <p className="text-xs text-slate-500 mt-1">Biểu đồ xếp chồng theo các nhóm bệnh đang được chọn ở bộ lọc Top {topLimit}.</p>
        </div>
        {stackedTopChartData.data.length === 0 ? (
          <EmptyChart loading={loading} label={t('dashboard.noPeriodData')} t={t} />
        ) : (
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={stackedTopChartData.data} barGap={2} margin={{ bottom: 32 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip contentStyle={{ borderRadius: '0.75rem', border: '1px solid #e2e8f0' }} />
              <Legend
                verticalAlign="bottom"
                content={(props) => (
                  <BilingualLegend
                    payload={props.payload as unknown as Array<{ value: string; color: string }>}
                    bilingualMap={bilingualMap}
                  />
                )}
              />
              {stackedTopChartData.groups.map((g, i) => (
                <Bar key={g} dataKey={g} stackId="a" fill={PIE_COLORS[i % PIE_COLORS.length]} radius={[2, 2, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h3 className="text-lg font-semibold text-slate-800">{t('dashboard.forecastResults')}</h3>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={forecastSearch}
                onChange={(e) => setForecastSearch(e.target.value)}
                placeholder={t('forecast.searchGroup')}
                className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white w-64"
              />
            </div>
            <span className="text-xs text-slate-400">
              {filteredForecast.length} / {forecast.length} {t('common.rows')}
            </span>
          </div>
        </div>
        {forecast.length === 0 ? (
          <p className="text-sm text-slate-500">{t('dashboard.noForecast')}</p>
        ) : filteredForecast.length === 0 ? (
          <p className="text-sm text-slate-500">{t('forecast.noMatch')}</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-2 w-8"></th>
                    <th className="py-2 pr-4">{t('col.period')}</th>
                    <th className="py-2 pr-4">{t('col.diseaseGroup')}</th>
                    <th className="py-2 pr-4 text-right">{t('col.previous')}</th>
                    <th className="py-2 pr-4 text-right">{t('col.predicted')}</th>
                    <th className="py-2 pr-4 text-right">{t('col.changePercent')}</th>
                    <th className="py-2 pr-4">{t('col.trend')}</th>
                    <th className="py-2">{t('col.risk')}</th>
                  </tr>
                </thead>
                <tbody>
                  {forecastPageRows.map((row, i) => {
                    const key = `${row.forecast_period}__${row.disease_group}`;
                    const open = expandedForecastKeys.has(key);
                    const ageRows = forecastDetails.filter(
                      (d) =>
                        d.forecast_period === row.forecast_period &&
                        d.disease_group === row.disease_group,
                    );
                    return (
                      <Fragment key={key}>
                        <tr
                          className="border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer"
                          onClick={() => {
                            setExpandedForecastKeys((cur) => {
                              const next = new Set(cur);
                              if (next.has(key)) next.delete(key);
                              else next.add(key);
                              return next;
                            });
                          }}
                        >
                          <td className="py-2 pr-2 text-slate-400">
                            <ChevronRight
                              size={14}
                              className={`transition-transform ${open ? 'rotate-90' : ''}`}
                            />
                          </td>
                          <td className="py-2 pr-4 font-medium text-slate-700">{row.forecast_period}</td>
                          <td className="py-2 pr-4">
                            <DiseaseLabelCell raw={row.disease_group} map={bilingualMap} />
                          </td>
                          <td className="py-2 pr-4 text-right">{row.previous_cases}</td>
                          <td className="py-2 pr-4 text-right font-semibold">{row.predicted_cases}</td>
                          <td className="py-2 pr-4 text-right">
                            {row.change_percent === null ? '—' : `${row.change_percent.toFixed(1)}%`}
                          </td>
                          <td className="py-2 pr-4 text-slate-600">{row.trend}</td>
                          <td className="py-2">
                            <span
                              className={`inline-block px-2 py-0.5 rounded-full border text-xs font-medium ${
                                RISK_COLORS[row.risk_level] ?? 'bg-slate-100 text-slate-700 border-slate-200'
                              }`}
                            >
                              {riskLabel(row.risk_level, t)}
                            </span>
                          </td>
                        </tr>
                        {open && (
                          <tr className="bg-slate-50">
                            <td colSpan={8} className="px-6 py-3">
                              {ageRows.length === 0 ? (
                                <p className="text-xs text-slate-500">
                                  {t('forecast.noDetails')}
                                </p>
                              ) : (
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="text-slate-500 border-b border-slate-200">
                                      <th className="py-1.5 px-2 text-left">{t('col.ageGroup')}</th>
                                      <th className="py-1.5 px-2 text-right">{t('col.previous')}</th>
                                      <th className="py-1.5 px-2 text-right">{t('col.predicted')}</th>
                                      <th className="py-1.5 px-2 text-right">{t('col.changePercent')}</th>
                                      <th className="py-1.5 px-2">{t('col.trend')}</th>
                                      <th className="py-1.5 px-2">{t('col.risk')}</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {sortAgeGroups(ageRows, (d) => d.age_group)
                                      .map((d) => (
                                        <tr key={d.id} className="border-b border-slate-100 last:border-0">
                                          <td className="py-1.5 px-2 font-medium text-slate-700">
                                            {d.age_group}
                                          </td>
                                          <td className="py-1.5 px-2 text-right">{d.previous_cases}</td>
                                          <td className="py-1.5 px-2 text-right font-semibold">
                                            {d.predicted_cases}
                                          </td>
                                          <td className="py-1.5 px-2 text-right">
                                            {d.change_percent === null
                                              ? '—'
                                              : `${d.change_percent.toFixed(1)}%`}
                                          </td>
                                          <td className="py-1.5 px-2 text-slate-600">{d.trend}</td>
                                          <td className="py-1.5 px-2">
                                            <span
                                              className={`inline-block px-2 py-0.5 rounded-full border text-[10px] ${
                                                RISK_COLORS[d.risk_level] ??
                                                'bg-slate-100 text-slate-700 border-slate-200'
                                              }`}
                                            >
                                              {riskLabel(d.risk_level, t)}
                                            </span>
                                          </td>
                                        </tr>
                                      ))}
                                  </tbody>
                                </table>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {/* Pagination + page size */}
            {filteredForecast.length > 0 && (
              <div className="flex items-center justify-between mt-4 text-sm gap-3 flex-wrap">
                <div className="flex items-center gap-2 text-slate-500">
                  <span>{t('common.pageSize')}:</span>
                  <select
                    value={forecastPageSize}
                    onChange={(e) => setForecastPageSize(Number(e.target.value))}
                    className="px-2 py-1 text-xs rounded border border-slate-200 bg-white"
                  >
                    {[10, 20, 50, 100, filteredForecast.length].filter((v, i, arr) =>
                      v > 0 && arr.indexOf(v) === i
                    ).map((n) => (
                      <option key={n} value={n}>
                        {n === filteredForecast.length && n > 100
                          ? `${t('common.all')} (${n})`
                          : n}
                      </option>
                    ))}
                  </select>
                  <span className="text-xs">
                    {t('common.showing')} {(forecastPage - 1) * forecastPageSize + 1}–
                    {Math.min(forecastPage * forecastPageSize, filteredForecast.length)} / {filteredForecast.length}
                  </span>
                </div>
                {forecastTotalPages > 1 && (
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-slate-500 mr-2">
                      {t('common.page')} {forecastPage} / {forecastTotalPages}
                    </span>
                    <button
                      onClick={() => setForecastPage(1)}
                      disabled={forecastPage === 1}
                      className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                    >
                      «
                    </button>
                    <button
                      onClick={() => setForecastPage((p) => Math.max(1, p - 1))}
                      disabled={forecastPage === 1}
                      className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                    >
                      ‹
                    </button>
                    <span className="px-3 py-1 text-xs text-slate-700">{forecastPage}</span>
                    <button
                      onClick={() => setForecastPage((p) => Math.min(forecastTotalPages, p + 1))}
                      disabled={forecastPage === forecastTotalPages}
                      className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                    >
                      ›
                    </button>
                    <button
                      onClick={() => setForecastPage(forecastTotalPages)}
                      disabled={forecastPage === forecastTotalPages}
                      className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                    >
                      »
                    </button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function EmptyChart({
  loading,
  label,
  t,
}: {
  loading: boolean;
  label: string;
  t: (k: string) => string;
}) {
  return (
    <div className="h-[300px] flex items-center justify-center text-slate-400 text-sm">
      {loading ? (
        <span className="inline-flex items-center gap-2">
          <Loader2 size={16} className="animate-spin" /> {t('common.loading')}
        </span>
      ) : (
        label
      )}
    </div>
  );
}
