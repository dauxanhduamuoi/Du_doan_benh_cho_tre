import { useCallback, useEffect, useMemo, useState, Fragment } from 'react';
import {
  TrendingUp,
  Loader2,
  RefreshCcw,
  PlayCircle,
  AlertTriangle,
  Activity,
  Layers,
  Calendar,
  Filter,
  Search,
  Download,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts';
import * as api from '@/lib/api';
import { addNotification } from '@/lib/notifications';
import { downloadReport, formatBytes } from '@/lib/reports';
import { useT } from '@/lib/i18n';
import { ensureBilingualMap, splitDiseaseLabel, fuzzyMatch } from '@/lib/disease';
import { sortAgeGroups } from '@/lib/age';
import DiseaseLabelCell from './common/DiseaseLabelCell';
import { useMinimalTheme } from '@/lib/useMinimalTheme';

const RISK_COLORS: Record<string, string> = {
  Cao: 'bg-red-100 text-red-700 border-red-200',
  'Trung bình': 'bg-amber-100 text-amber-700 border-amber-200',
  Thấp: 'bg-emerald-100 text-emerald-700 border-emerald-200',
};

// Tông pastel nhẹ cho thanh "Dự báo", kèm stroke đậm hơn để vẫn rõ.
const RISK_FILL: Record<string, string> = {
  Cao: '#fecaca',
  'Trung bình': '#fde68a',
  Thấp: '#bbf7d0',
};

const RISK_STROKE: Record<string, string> = {
  Cao: '#f87171',
  'Trung bình': '#fbbf24',
  Thấp: '#34d399',
};

// Màu trung tính cho thanh "Kỳ trước" — không tranh sự chú ý với "Dự báo".
const PREVIOUS_FILL = '#e2e8f0';
const PREVIOUS_STROKE = '#cbd5e1';

type RiskFilter = 'all' | 'Cao' | 'Trung bình' | 'Thấp';

// BE trả tiếng Việt → dịch cho hiển thị.
function riskLabel(level: string, t: (k: string) => string): string {
  if (level === 'Cao') return t('common.high');
  if (level === 'Trung bình') return t('common.medium');
  if (level === 'Thấp') return t('common.low');
  return level;
}

export default function Forecast() {
  const isMinimalTheme = useMinimalTheme();
  const t = useT();
  const [summary, setSummary] = useState<api.ForecastGroupSummary[]>([]);
  const [details, setDetails] = useState<api.ForecastResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Chỉ chạy dự báo 1 tháng — đã bỏ tuỳ chọn 2/3 tháng theo yêu cầu.
  const horizon = 1 as const;
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [summarySearchTerm, setSummarySearchTerm] = useState('');
  const [debouncedSummarySearch, setDebouncedSummarySearch] = useState('');
  const [selectedPeriod, setSelectedPeriod] = useState<string>('all');
  // Map VN→EN từ BE để search có thể match cả 2 ngôn ngữ.
  const [bilingualMap, setBilingualMap] = useState<Record<string, string>>({});

  // Debounce search 200ms để tránh re-render mỗi keystroke khi data lớn.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(searchTerm.trim()), 200);
    return () => clearTimeout(id);
  }, [searchTerm]);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedSummarySearch(summarySearchTerm.trim()), 200);
    return () => clearTimeout(id);
  }, [summarySearchTerm]);

  useEffect(() => {
    ensureBilingualMap().then(setBilingualMap).catch(() => undefined);
  }, []);

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, d] = await Promise.all([
        api.getForecastGroupSummary().catch(() => [] as api.ForecastGroupSummary[]),
        api.getForecastResults().catch(() => [] as api.ForecastResult[]),
      ]);
      setSummary(s);
      setDetails(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRun = async () => {
    setRunning(true);
    try {
      await api.runForecast('auto', horizon);
      // Lấy dữ liệu mới trực tiếp từ API thay vì đọc state `summary` cũ
      // (setSummary trong load() là async nên closure này thấy giá trị trước đó).
      const [s, d] = await Promise.all([
        api.getForecastGroupSummary().catch(() => [] as api.ForecastGroupSummary[]),
        api.getForecastResults().catch(() => [] as api.ForecastResult[]),
      ]);
      setSummary(s);
      setDetails(d);
      const high = s.filter((r) => r.risk_level === 'Cao').length;
      addNotification({
        type: 'forecast',
        severity: high > 0 ? 'warning' : 'info',
        title: t('forecast.done'),
        description: `${t('forecast.horizon')}: ${horizon} ${t('forecast.monthUnit')} · ${t('forecast.highRisk')}: ${high}`,
      });
      showToast('success', t('forecast.done'));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      addNotification({
        type: 'forecast',
        severity: 'critical',
        title: t('forecast.failed'),
        description: msg,
      });
      showToast('error', msg);
    } finally {
      setRunning(false);
    }
  };

  const periods = useMemo(() => {
    const set = new Set<string>();
    for (const r of summary) set.add(r.forecast_period);
    for (const r of details) set.add(r.forecast_period);
    return Array.from(set).sort();
  }, [summary, details]);

  useEffect(() => {
    if (selectedPeriod === 'all') return;
    if (periods.length > 0 && !periods.includes(selectedPeriod)) {
      setSelectedPeriod(periods[0]);
    }
  }, [periods, selectedPeriod]);

  const filteredSummary = useMemo(() => {
    return summary.filter((r) => {
      if (selectedPeriod !== 'all' && r.forecast_period !== selectedPeriod) return false;
      if (riskFilter !== 'all' && r.risk_level !== riskFilter) return false;
      if (debouncedSearch) {
        // Search match cả tên VN gốc lẫn tên EN tách ra.
        const lbl = splitDiseaseLabel(r.disease_group, bilingualMap);
        const haystack = `${lbl.vi} ${lbl.en ?? ''}`;
        if (!fuzzyMatch(haystack, debouncedSearch)) return false;
      }
      return true;
    });
  }, [summary, selectedPeriod, riskFilter, debouncedSearch, bilingualMap]);

  const riskCounts = useMemo(() => {
    const base: Record<'Cao' | 'Trung bình' | 'Thấp', number> = { Cao: 0, 'Trung bình': 0, Thấp: 0 };
    for (const r of summary) {
      if (r.risk_level in base) base[r.risk_level as keyof typeof base] += 1;
    }
    return base;
  }, [summary]);

  const totalPredicted = useMemo(
    () => summary.reduce((a, b) => a + b.predicted_cases, 0),
    [summary],
  );

  // Liệt kê các tháng đang được dự báo CHO LẦN CHẠY HIỆN TẠI.
  // Lấy `forecast_horizon` (1) kỳ kế tiếp ngay sau kỳ thật mới nhất trong
  // dataset, không đi tìm trong DB (vì DB có thể còn kết quả cũ từ lần
  // chạy horizon khác → dễ gây nhầm).
  const forecastedPeriods = useMemo(() => {
    if (periods.length === 0) return [];
    // Tìm kỳ "thật" cuối cùng = kỳ < tháng hiện tại trong tập periods.
    const now = new Date();
    const currentKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    const past = periods.filter((p) => p < currentKey);
    const future = periods.filter((p) => p >= currentKey);

    // Nếu đã có kết quả forecast cho tương lai → hiển thị tối đa `horizon` kỳ
    // gần nhất (lọc trùng số horizon đang chọn).
    if (future.length > 0) {
      return future.slice(0, horizon);
    }
    // Fallback: chưa có forecast nào, gợi ý kỳ kế tiếp dựa trên `past`.
    if (past.length > 0) {
      const last = past[past.length - 1];
      const [y, m] = last.split('-').map(Number);
      const next = new Date(y, m, 1); // m = 0-indexed nên đây là tháng kế tiếp
      return [`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`];
    }
    return periods.slice(-1);
  }, [periods, horizon]);

  const chartData = useMemo(() => {
    // Khi xem nhiều kỳ, kèm kỳ vào label để không bị trùng nhãn trên trục Y
    // (cùng nhóm bệnh ở nhiều kỳ khác nhau sẽ là 2 dòng khác nhau).
    const showPeriod = selectedPeriod === 'all' && periods.length > 1;
    return filteredSummary
      .slice()
      .sort((a, b) => b.predicted_cases - a.predicted_cases)
      .slice(0, 10)
      .map((r) => {
        const groupShort =
          r.disease_group.length > 28 ? r.disease_group.slice(0, 27) + '…' : r.disease_group;
        return {
          name: showPeriod ? `${r.forecast_period} · ${groupShort}` : groupShort,
          predicted: r.predicted_cases,
          previous: r.previous_cases,
          risk: r.risk_level,
        };
      });
  }, [filteredSummary, selectedPeriod, periods]);

  // Pagination cho bảng "Tổng hợp theo nhóm bệnh".
  const [summaryPage, setSummaryPage] = useState(1);
  const [summaryPageSize, setSummaryPageSize] = useState<number | 'custom'>(20);
  const [summaryCustomSize, setSummaryCustomSize] = useState('20');
  // Mỗi (period × disease) trong summary có thể expand ra chi tiết theo tuổi
  // (giống bảng "Kết quả dự báo mới nhất" ở Tổng quan).
  const [summaryExpandedKeys, setSummaryExpandedKeys] = useState<Set<string>>(new Set());

  const summaryTableFiltered = useMemo(() => {
    if (!debouncedSummarySearch) return filteredSummary;
    return filteredSummary.filter((r) => {
      const lbl = splitDiseaseLabel(r.disease_group, bilingualMap);
      const haystack = `${r.forecast_period} ${lbl.vi} ${lbl.en ?? ''}`;
      return fuzzyMatch(haystack, debouncedSummarySearch);
    });
  }, [filteredSummary, debouncedSummarySearch, bilingualMap]);

  useEffect(() => {
    setSummaryPage(1);
  }, [summaryTableFiltered.length, summaryPageSize]);

  const summaryEffectiveSize = useMemo(() => {
    if (summaryPageSize === 'custom') {
      const n = Math.max(1, Math.min(1000, parseInt(summaryCustomSize, 10) || 20));
      return n;
    }
    return summaryPageSize;
  }, [summaryPageSize, summaryCustomSize]);

  const summaryTotalPages = Math.max(1, Math.ceil(summaryTableFiltered.length / summaryEffectiveSize));
  const summaryPageRows = useMemo(() => {
    const start = (summaryPage - 1) * summaryEffectiveSize;
    return summaryTableFiltered.slice(start, start + summaryEffectiveSize);
  }, [summaryTableFiltered, summaryPage, summaryEffectiveSize]);

  const summaryAllExpanded = useMemo(
    () =>
      summaryTableFiltered.length > 0 &&
      summaryTableFiltered.every((row) => summaryExpandedKeys.has(`${row.forecast_period}__${row.disease_group}`)),
    [summaryTableFiltered, summaryExpandedKeys],
  );

  const toggleAllSummary = () => {
    if (summaryAllExpanded) {
      setSummaryExpandedKeys(new Set());
      return;
    }
    setSummaryExpandedKeys(new Set(summaryTableFiltered.map((row) => `${row.forecast_period}__${row.disease_group}`)));
  };

  const handleExport = () => {
    const rows = summaryTableFiltered.map((r) => ({
      forecast_period: r.forecast_period,
      disease_group: r.disease_group,
      previous_cases: r.previous_cases,
      predicted_cases: r.predicted_cases,
      change_percent: r.change_percent,
      trend: r.trend,
      risk_level: riskLabel(r.risk_level, t),
    }));
    const result = downloadReport(
      {
        title: 'Forecast-disease-group',
        subtitle: selectedPeriod === 'all' ? t('common.all') : `${t('col.period')} ${selectedPeriod}`,
        generatedAt: new Date().toISOString(),
        columns: [
          { key: 'forecast_period', label: t('col.period') },
          { key: 'disease_group', label: t('col.diseaseGroup') },
          { key: 'previous_cases', label: t('col.previous'), align: 'right' },
          { key: 'predicted_cases', label: t('col.predicted'), align: 'right' },
          {
            key: 'change_percent',
            label: t('col.changePercent'),
            align: 'right',
            format: (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`),
          },
          { key: 'trend', label: t('col.trend') },
          { key: 'risk_level', label: t('col.risk') },
        ],
        rows: rows as unknown as Record<string, unknown>[],
        summary: [
          { label: t('common.rows'), value: rows.length },
          { label: t('forecast.totalPredicted'), value: rows.reduce((a, b) => a + b.predicted_cases, 0) },
        ],
      },
      'csv',
    );
    showToast('success', `${result.filename} (${formatBytes(result.sizeBytes)})`);
  };

  const isEmpty = summary.length === 0 && details.length === 0;

  return (
    <div className="space-y-6">
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 flex items-start gap-2 px-4 py-3 rounded-xl shadow-lg border min-w-[280px] max-w-sm ${
            toast.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-red-50 border-red-200 text-red-800'
          }`}
        >
          {toast.type === 'success' ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
          <span className="text-sm flex-1 break-words">{toast.message}</span>
        </div>
      )}

      {/* Action bar */}
      <div className="bg-white rounded-xl p-4 border border-slate-200 shadow-sm flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">{t('forecast.horizon')}</span>
          <span className="px-3 py-1.5 text-sm rounded-lg bg-blue-50 border border-blue-200 text-blue-700 font-medium">
            1 {t('forecast.monthUnit')}
          </span>
        </div>

        <button
          onClick={handleRun}
          disabled={running}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-60"
        >
          {running ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
          {running ? t('forecast.running') : t('forecast.run')}
        </button>

        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
          {t('forecast.refresh')}
        </button>

        <button
          onClick={handleExport}
          disabled={filteredSummary.length === 0}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40 ml-auto"
        >
          <Download size={16} />
          {t('forecast.exportCsv')}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm flex items-start gap-2">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {isEmpty && !loading && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-3 text-sm">
          {t('forecast.empty')}
        </div>
      )}

      {/* Banner hiển thị các tháng đang được dự báo */}
      {!isEmpty && forecastedPeriods.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 text-blue-800 rounded-xl px-4 py-3 text-sm flex items-center gap-2 flex-wrap">
          <Calendar size={16} className="text-blue-600 shrink-0" />
          <span>{t('forecast.forecastingFor')}:</span>
          <div className="flex gap-1.5 flex-wrap">
            {forecastedPeriods.map((p) => (
              <span
                key={p}
                className="inline-block px-2 py-0.5 rounded-full bg-white border border-blue-200 text-blue-700 font-medium text-xs"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <StatCard
          icon={Activity}
          label={t('forecast.totalGroups')}
          value={summary.length}
          iconBg="bg-blue-100"
          iconColor="text-blue-600"
          borderColor="border-l-blue-500"
        />
        <StatCard
          icon={TrendingUp}
          label={t('forecast.totalPredicted')}
          value={totalPredicted}
          iconBg="bg-emerald-100"
          iconColor="text-emerald-600"
          borderColor="border-l-emerald-500"
        />
        <StatCard
          icon={AlertTriangle}
          label={t('forecast.highRisk')}
          value={riskCounts.Cao}
          iconBg="bg-red-100"
          iconColor="text-red-600"
          borderColor="border-l-red-500"
        />
        <StatCard
          icon={Layers}
          label={t('forecast.totalPeriods')}
          value={periods.length}
          iconBg="bg-purple-100"
          iconColor="text-purple-600"
          borderColor="border-l-purple-500"
        />
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl p-4 border border-slate-200 shadow-sm flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Calendar size={16} className="text-slate-500" />
          <span className="text-sm text-slate-500">{t('col.period')}</span>
          <select
            value={selectedPeriod}
            onChange={(e) => setSelectedPeriod(e.target.value)}
            className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('common.all')}</option>
            {periods.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <Filter size={16} className="text-slate-500" />
          <span className="text-sm text-slate-500">{t('forecast.risk')}</span>
          {(['all', 'Cao', 'Trung bình', 'Thấp'] as RiskFilter[]).map((r) => (
            <button
              key={r}
              onClick={() => setRiskFilter(r)}
              className={`px-3 py-1.5 text-xs rounded-full border transition-all ${
                riskFilter === r
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
              }`}
            >
              {r === 'all' ? t('common.all') : riskLabel(r, t)}
            </button>
          ))}
        </div>

        <div className="relative ml-auto">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={t('forecast.searchGroup')}
            className="pl-9 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white w-56"
          />
        </div>
      </div>

      {/* Chart */}
      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h3 className="text-lg font-semibold text-slate-800">
            {t('forecast.topChart')}
            {selectedPeriod !== 'all' && (
              <span className="text-sm text-slate-500 ml-2">· {t('col.period')} {selectedPeriod}</span>
            )}
          </h3>
          {/* Chú thích màu rủi ro để người xem hiểu mã màu thanh "Dự báo" */}
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {(['Cao', 'Trung bình', 'Thấp'] as const).map((r) => (
              <span key={r} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-3 rounded-sm border"
                  style={{ backgroundColor: RISK_FILL[r], borderColor: RISK_STROKE[r] }}
                />
                {riskLabel(r, t)}
              </span>
            ))}
          </div>
        </div>
        {chartData.length === 0 ? (
          <EmptyChart loading={loading} label={t('forecast.noMatch')} t={t} />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(320, chartData.length * 40 + 80)}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ left: 40, right: 32, top: 8, bottom: 8 }}
              barCategoryGap={10}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={true} vertical={false} />
              <XAxis type="number" tick={{ fontSize: 12, fill: '#64748b' }} stroke="#cbd5e1" />
              <YAxis
                dataKey="name"
                type="category"
                tick={{ fontSize: 11, fill: '#475569' }}
                stroke="#cbd5e1"
                width={200}
              />
              <Tooltip
                cursor={{ fill: '#f8fafc' }}
                contentStyle={{
                  borderRadius: '0.75rem',
                  border: '1px solid #e2e8f0',
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar
                dataKey="previous"
                name={t('forecast.previous')}
                fill={PREVIOUS_FILL}
                stroke={PREVIOUS_STROKE}
                strokeWidth={1}
                radius={[0, 4, 4, 0]}
                barSize={14}
                isAnimationActive={!isMinimalTheme}
              >
                <LabelList dataKey="previous" position="right" style={{ fontSize: 10, fill: '#94a3b8' }} />
              </Bar>
              <Bar
                dataKey="predicted"
                name={t('forecast.predicted')}
                strokeWidth={1}
                radius={[0, 4, 4, 0]}
                barSize={14}
                isAnimationActive={!isMinimalTheme}
              >
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={RISK_FILL[entry.risk] ?? '#dbeafe'}
                    stroke={RISK_STROKE[entry.risk] ?? '#93c5fd'}
                  />
                ))}
                <LabelList dataKey="predicted" position="right" style={{ fontSize: 11, fill: '#475569', fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Summary table */}
      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h3 className="text-lg font-semibold text-slate-800">{t('forecast.summaryTable')}</h3>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={summarySearchTerm}
                onChange={(e) => setSummarySearchTerm(e.target.value)}
                placeholder={t('forecast.searchGroup')}
                className="w-60 pl-9 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
              />
            </div>
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <span>{t('common.pageSize')}:</span>
              <select
                value={summaryPageSize === 'custom' ? 'custom' : String(summaryPageSize)}
                onChange={(e) => {
                  const v = e.target.value;
                  setSummaryPageSize(v === 'custom' ? 'custom' : Number(v));
                }}
                className="px-2 py-1 text-xs rounded border border-slate-200 bg-white"
              >
                {[10, 20, 50, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
                <option value="custom">{t('common.custom') ?? 'Tùy chỉnh'}</option>
              </select>
              {summaryPageSize === 'custom' && (
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={summaryCustomSize}
                  onChange={(e) => setSummaryCustomSize(e.target.value)}
                  className="w-20 px-2 py-1 text-xs rounded border border-slate-200 bg-white"
                />
              )}
            </div>
            <button
              onClick={toggleAllSummary}
              disabled={summaryTableFiltered.length === 0}
              className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              {summaryAllExpanded ? 'Thu gọn tất cả' : 'Mở rộng tất cả'}
            </button>
            <span className="text-xs text-slate-400">
              {summaryTableFiltered.length} {t('common.rows')}
            </span>
          </div>
        </div>
        {summaryTableFiltered.length === 0 ? (
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
                  {summaryPageRows.map((row) => {
                    const key = `${row.forecast_period}__${row.disease_group}`;
                    const open = summaryExpandedKeys.has(key);
                    const ageRows = details.filter(
                      (d) =>
                        d.forecast_period === row.forecast_period &&
                        d.disease_group === row.disease_group,
                    );
                    return (
                      <Fragment key={key}>
                        <tr
                          className="border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer"
                          onClick={() => {
                            setSummaryExpandedKeys((cur) => {
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
                                <p className="text-xs text-slate-500">{t('forecast.noDetails')}</p>
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
                                    {sortAgeGroups(ageRows, (d) => d.age_group).map((d) => (
                                      <tr key={d.id} className="border-b border-slate-100 last:border-0">
                                        <td className="py-1.5 px-2 font-medium text-slate-700">{d.age_group}</td>
                                        <td className="py-1.5 px-2 text-right">{d.previous_cases}</td>
                                        <td className="py-1.5 px-2 text-right font-semibold">{d.predicted_cases}</td>
                                        <td className="py-1.5 px-2 text-right">
                                          {d.change_percent === null ? '—' : `${d.change_percent.toFixed(1)}%`}
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
            {/* Pagination */}
            <div className="flex items-center justify-between mt-4 text-sm gap-3 flex-wrap">
              <span className="text-xs text-slate-500">
                {t('common.showing')} {(summaryPage - 1) * summaryEffectiveSize + 1}–
                {Math.min(summaryPage * summaryEffectiveSize, summaryTableFiltered.length)} / {summaryTableFiltered.length}
              </span>
              {summaryTotalPages > 1 && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-slate-500 mr-2">
                    {t('common.page')} {summaryPage} / {summaryTotalPages}
                  </span>
                  <button
                    onClick={() => setSummaryPage(1)}
                    disabled={summaryPage === 1}
                    className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                  >
                    «
                  </button>
                  <button
                    onClick={() => setSummaryPage((p) => Math.max(1, p - 1))}
                    disabled={summaryPage === 1}
                    className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                  >
                    ‹
                  </button>
                  <span className="px-3 py-1 text-xs text-slate-700">{summaryPage}</span>
                  <button
                    onClick={() => setSummaryPage((p) => Math.min(summaryTotalPages, p + 1))}
                    disabled={summaryPage === summaryTotalPages}
                    className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                  >
                    ›
                  </button>
                  <button
                    onClick={() => setSummaryPage(summaryTotalPages)}
                    disabled={summaryPage === summaryTotalPages}
                    className="px-2 py-1 text-xs rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                  >
                    »
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

    </div>
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
  icon: typeof Activity;
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
          <p className="text-3xl font-bold text-slate-800 mt-1">{value.toLocaleString()}</p>
        </div>
        <div className={`p-3 rounded-xl ${iconBg}`}>
          <Icon className={iconColor} size={22} />
        </div>
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
    <div className="h-[360px] flex items-center justify-center text-slate-400 text-sm">
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
