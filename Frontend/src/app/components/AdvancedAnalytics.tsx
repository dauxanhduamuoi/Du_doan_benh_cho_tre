import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, BarChart3, Check, ChevronDown, Loader2, RefreshCcw, Search } from 'lucide-react';
import * as api from '@/lib/api';
import DiseaseLabelCell from './common/DiseaseLabelCell';
import { ensureBilingualMap, fuzzyMatch, splitDiseaseLabel } from '@/lib/disease';
import { useMinimalTheme } from '@/lib/useMinimalTheme';

type AnalysisMode = 'monthly' | 'gender' | 'trend';
type GenderScope = 'month' | 'year' | 'all';
type TrendTooltipEntry = {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string | Array<number | string> | null;
  color?: string;
  stroke?: string;
};
type TrendHoverPoint = {
  key: string;
  period: string;
  clientX: number;
  clientY: number;
};

const COLORS = [
  '#2563eb',
  '#dc2626',
  '#16a34a',
  '#9333ea',
  '#ea580c',
  '#0891b2',
  '#be123c',
  '#7c3aed',
  '#ca8a04',
  '#0f766e',
  '#4338ca',
  '#64748b',
];

const MODE_COPY: Record<AnalysisMode, { title: string; description: string }> = {
  monthly: {
    title: 'Phân tích nhóm bệnh theo tháng',
    description: 'Tra cứu nhanh một tháng/năm để xem top nhóm bệnh, tỷ trọng và mức thay đổi so với tháng trước.',
  },
  gender: {
    title: 'Phân tích bệnh theo giới tính',
    description: 'Xem phân bố số ca nam/nữ và các nhóm bệnh nổi bật theo giới tính trong tháng/năm đã chọn.',
  },
  trend: {
    title: 'Xu hướng nhóm bệnh theo thời gian',
    description: 'Chọn một hoặc nhiều nhóm bệnh để xem xu hướng qua các tháng và so sánh cùng tháng giữa nhiều năm.',
  },
};

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

function monthLabel(m: number): string {
  return `Tháng ${m}`;
}

function EmptyBox({ loading, label }: { loading: boolean; label: string }) {
  return (
    <div className="flex h-[240px] items-center justify-center text-sm text-slate-400">
      {loading ? (
        <span className="inline-flex items-center gap-2">
          <Loader2 size={16} className="animate-spin" /> Đang tải dữ liệu...
        </span>
      ) : (
        label
      )}
    </div>
  );
}

function TrendLineTooltip({
  hoverPoint,
  series,
  chartData,
}: {
  hoverPoint: TrendHoverPoint | null;
  series: Array<{ key: string; label: string; color: string }>;
  chartData: Array<Record<string, number | string>>;
}) {
  if (!hoverPoint) return null;

  const numericValue = (value: TrendTooltipEntry['value']) => {
    if (Array.isArray(value)) return null;
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const periodRow = chartData.find((row) => String(row.period) === hoverPoint.period);
  const hoveredValue = numericValue(periodRow?.[hoverPoint.key]);
  if (hoveredValue === null) return null;
  const rows = series
    .map((item) => ({
      ...item,
      value: numericValue(periodRow?.[item.key]),
    }))
    .filter((item) => item.value === hoveredValue);
  if (rows.length === 0) return null;

  const viewportWidth = typeof window === 'undefined' ? 1200 : window.innerWidth;
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight;
  const left = Math.min(hoverPoint.clientX + 14, Math.max(16, viewportWidth - 360));
  const top = Math.min(hoverPoint.clientY + 14, Math.max(16, viewportHeight - 180));

  return (
    <div
      className="pointer-events-none fixed z-[9999] max-w-sm rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-xl"
      style={{ left, top }}
    >
      <div className="mb-2 border-b border-slate-100 pb-1 text-xs font-semibold text-slate-500">{hoverPoint.period}</div>
      <div className="space-y-1.5">
        {rows.map((item) => (
          <div key={item.key} className="flex items-start gap-2">
            <span
              className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            <div className="min-w-0">
              <div className="font-medium leading-5 text-slate-700">{item.label}</div>
              <div className="text-xs font-semibold text-slate-500">{item.value?.toLocaleString()} ca</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendPointDot({
  cx,
  cy,
  payload,
  value,
  dataKey,
  color,
  dimmed = false,
  setHoverPoint,
}: {
  cx?: number | string;
  cy?: number | string;
  payload?: Record<string, number | string>;
  value?: number | string | null;
  dataKey: string;
  color: string;
  dimmed?: boolean;
  setHoverPoint: (point: TrendHoverPoint | null) => void;
}) {
  const x = Number(cx);
  const y = Number(cy);
  if (!Number.isFinite(x) || !Number.isFinite(y) || value === null || value === undefined || !payload?.period) {
    return null;
  }

  const setPoint = (event: ReactMouseEvent<SVGGElement>) =>
    setHoverPoint({
      key: dataKey,
      period: String(payload.period),
      clientX: event.clientX,
      clientY: event.clientY,
    });

  return (
    <g
      onMouseEnter={setPoint}
      onMouseMove={setPoint}
      onMouseLeave={() => setHoverPoint(null)}
    >
      <circle cx={x} cy={y} r={7} fill="transparent" />
      <circle
        cx={x}
        cy={y}
        r={dimmed ? 3 : 4}
        fill={dimmed ? '#cbd5e1' : color}
        opacity={dimmed ? 0.55 : 1}
        stroke="#fff"
        strokeWidth={1.5}
      />
    </g>
  );
}

function filterPeriodOptions(periods: api.DashboardPeriodOption[], search: string) {
  const q = search.trim().toLowerCase();
  const rows = q
    ? periods.filter((p) => `${p.period} ${p.year} ${p.month} ${p.season}`.toLowerCase().includes(q))
    : periods;
  return rows.slice().reverse();
}

export default function AdvancedAnalytics({ mode = 'monthly' }: { mode?: AnalysisMode }) {
  const isMinimalTheme = useMinimalTheme();
  const [periods, setPeriods] = useState<api.DashboardPeriodOption[]>([]);
  const [diseases, setDiseases] = useState<api.DashboardDiseaseGroupOption[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState('');
  const [selectedDisease, setSelectedDisease] = useState('');
  const [selectedDiseases, setSelectedDiseases] = useState<string[]>([]);
  const [genderTotalScope, setGenderTotalScope] = useState<GenderScope>('month');
  const [selectedGenderTotalPeriod, setSelectedGenderTotalPeriod] = useState('');
  const [selectedGenderTotalYear, setSelectedGenderTotalYear] = useState<number | null>(null);
  const [genderDiseaseScope, setGenderDiseaseScope] = useState<GenderScope>('month');
  const [selectedGenderDiseasePeriod, setSelectedGenderDiseasePeriod] = useState('');
  const [selectedGenderDiseaseYear, setSelectedGenderDiseaseYear] = useState<number | null>(null);
  const [searchPeriod, setSearchPeriod] = useState('');
  const [searchGenderTotalPeriod, setSearchGenderTotalPeriod] = useState('');
  const [searchGenderDiseasePeriod, setSearchGenderDiseasePeriod] = useState('');
  const [searchDisease, setSearchDisease] = useState('');
  const [limit, setLimit] = useState(10);

  const [summary, setSummary] = useState<api.SummaryCardResponse | null>(null);
  const [topByMonth, setTopByMonth] = useState<api.TopDiseaseGroupByMonth[]>([]);
  const [percentage, setPercentage] = useState<api.DiseasePercentageByMonth[]>([]);
  const [comparison, setComparison] = useState<api.MonthlyComparisonRow[]>([]);
  const [genderCases, setGenderCases] = useState<api.CasesByGenderRow[]>([]);
  const [genderComparison, setGenderComparison] = useState<api.DiseaseByGenderRow | null>(null);
  const [trend, setTrend] = useState<api.DiseaseTrendRow[]>([]);
  const [yearOverYear, setYearOverYear] = useState<api.YearOverYearRow[]>([]);

  const [bilingualMap, setBilingualMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [initLoading, setInitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredTrendPoint, setHoveredTrendPoint] = useState<TrendHoverPoint | null>(null);
  const [highlightedTrendDiseases, setHighlightedTrendDiseases] = useState<string[]>([]);

  const copy = MODE_COPY[mode];

  useEffect(() => {
    ensureBilingualMap().then(setBilingualMap).catch(() => undefined);
  }, []);

  useEffect(() => {
    let alive = true;
    setInitLoading(true);
    Promise.all([api.getDashboardPeriods(), api.getDashboardDiseaseGroups()])
      .then(([periodRows, diseaseRows]) => {
        if (!alive) return;
        setPeriods(periodRows);
        setDiseases(diseaseRows);
        const latestPeriod = periodRows[periodRows.length - 1];
        setSelectedPeriod(latestPeriod?.period ?? '');
        setSelectedGenderTotalPeriod(latestPeriod?.period ?? '');
        setSelectedGenderDiseasePeriod(latestPeriod?.period ?? '');
        setSelectedGenderTotalYear(latestPeriod?.year ?? null);
        setSelectedGenderDiseaseYear(latestPeriod?.year ?? null);
        setSelectedDisease(diseaseRows[0]?.disease_group ?? '');
        setSelectedDiseases(diseaseRows[0]?.disease_group ? [diseaseRows[0].disease_group] : []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        if (alive) setInitLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const selectedPeriodInfo = useMemo(
    () => periods.find((p) => p.period === selectedPeriod),
    [periods, selectedPeriod],
  );

  const filteredPeriods = useMemo(() => {
    const q = searchPeriod.trim().toLowerCase();
    if (!q) return periods.slice().reverse();
    return periods
      .filter((p) => `${p.period} ${p.year} ${p.month} ${p.season}`.toLowerCase().includes(q))
      .slice()
      .reverse();
  }, [periods, searchPeriod]);

  const genderTotalPeriodOptions = useMemo(
    () => filterPeriodOptions(periods, searchGenderTotalPeriod),
    [periods, searchGenderTotalPeriod],
  );

  const genderDiseasePeriodOptions = useMemo(
    () => filterPeriodOptions(periods, searchGenderDiseasePeriod),
    [periods, searchGenderDiseasePeriod],
  );

  const filteredDiseaseOptions = useMemo(() => {
    const q = searchDisease.trim();
    if (!q) return diseases.slice(0, 150);
    return diseases.filter((d) => fuzzyMatch(d.disease_group, q)).slice(0, 150);
  }, [diseases, searchDisease]);

  const yearOptions = useMemo(
    () => Array.from(new Set(periods.map((p) => p.year))).sort((a, b) => b - a),
    [periods],
  );

  const loadAnalysis = useCallback(async () => {
    if (!selectedPeriod) return;
    const disease = selectedDisease || diseases[0]?.disease_group;
    const month = selectedPeriodInfo?.month ?? Number(selectedPeriod.slice(5, 7));

    setLoading(true);
    setError(null);
    try {
      if (mode === 'monthly') {
        const [summaryCard, topMonthRows, percentRows, compareRows] = await Promise.all([
          api.getSummaryCard(selectedPeriod),
          api.getTopDiseaseGroupsByMonth(selectedPeriod, limit),
          api.getDiseasePercentageByMonth(selectedPeriod, limit),
          api.getMonthlyComparison(selectedPeriod, limit),
        ]);
        setSummary(summaryCard);
        setTopByMonth(topMonthRows);
        setPercentage(percentRows);
        setComparison(compareRows);
      }

      if (mode === 'gender') {
        const totalParams =
          genderTotalScope === 'month'
            ? { period: selectedGenderTotalPeriod }
            : genderTotalScope === 'year'
              ? { year: selectedGenderTotalYear ?? undefined }
              : {};

        const compareParams =
          genderDiseaseScope === 'month'
            ? { period: selectedGenderDiseasePeriod, diseaseGroup: disease, limit: 1 }
            : genderDiseaseScope === 'year'
              ? { year: selectedGenderDiseaseYear ?? undefined, diseaseGroup: disease, limit: 1 }
              : { diseaseGroup: disease, limit: 1 };

        const [genderRows, comparisonRows] = await Promise.all([
          api.getCasesByGender(totalParams),
          api.getDiseaseByGender(compareParams),
        ]);
        setGenderCases(genderRows);
        setGenderComparison(comparisonRows[0] ?? null);
      }

      if (mode === 'trend') {
        const diseaseList = selectedDiseases.length > 0 ? selectedDiseases : disease ? [disease] : [];
        const [trendLists, yoyLists] = await Promise.all([
          Promise.all(
            diseaseList.map((dg) =>
              api.getDiseaseTrend({ diseaseGroup: dg, startPeriod: periods[0]?.period, endPeriod: selectedPeriod }),
            ),
          ),
          Promise.all(diseaseList.map((dg) => api.getYearOverYear(month, dg))),
        ]);
        setTrend(trendLists.flat());
        setYearOverYear(yoyLists.flat());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [
    mode,
    selectedPeriod,
    selectedDisease,
    selectedDiseases,
    diseases,
    selectedPeriodInfo,
    limit,
    periods,
    genderTotalScope,
    selectedGenderTotalPeriod,
    selectedGenderTotalYear,
    genderDiseaseScope,
    selectedGenderDiseasePeriod,
    selectedGenderDiseaseYear,
  ]);

  useEffect(() => {
    if (selectedPeriod) loadAnalysis();
  }, [selectedPeriod, selectedDisease, limit, loadAnalysis]);

  useEffect(() => {
    setHighlightedTrendDiseases((prev) => prev.filter((disease) => selectedDiseases.includes(disease)));
  }, [selectedDiseases]);

  const topByMonthChart = useMemo(
    () =>
      topByMonth.map((row, idx) => ({
        ...row,
        label: splitDiseaseLabel(row.disease_group, bilingualMap).vi,
        color: COLORS[idx % COLORS.length],
      })),
    [topByMonth, bilingualMap],
  );

  const percentChart = useMemo(
    () =>
      percentage.map((row, idx) => ({
        ...row,
        label: splitDiseaseLabel(row.disease_group, bilingualMap).vi,
        color: COLORS[idx % COLORS.length],
      })),
    [percentage, bilingualMap],
  );

  const comparisonChart = useMemo(
    () =>
      comparison.slice(0, Math.min(limit, 12)).map((row) => ({
        disease_group: splitDiseaseLabel(row.disease_group, bilingualMap).vi,
        current_cases: row.current_cases,
        previous_cases: row.previous_cases,
      })),
    [comparison, bilingualMap, limit],
  );

  const trendTitle = selectedDisease ? splitDiseaseLabel(selectedDisease, bilingualMap).vi : '-';

  // Danh sách nhóm bệnh đang vẽ + màu cố định theo thứ tự chọn.
  const trendSeries = useMemo(
    () =>
      selectedDiseases.map((dg, idx) => ({
        key: dg,
        label: splitDiseaseLabel(dg, bilingualMap).vi,
        color: COLORS[idx % COLORS.length],
      })),
    [selectedDiseases, bilingualMap],
  );
  const highlightedTrendSet = useMemo(() => new Set(highlightedTrendDiseases), [highlightedTrendDiseases]);
  const hasTrendHighlight = highlightedTrendDiseases.length > 0;

  const toggleTrendHighlight = useCallback((diseaseGroup: string) => {
    setHighlightedTrendDiseases((prev) =>
      prev.includes(diseaseGroup)
        ? prev.filter((item) => item !== diseaseGroup)
        : [...prev, diseaseGroup],
    );
  }, []);

  // Pivot trend rows (1 dòng / period, mỗi nhóm bệnh là 1 cột case_count).
  const trendChart = useMemo(() => {
    const byPeriod = new Map<string, Record<string, number | string>>();
    for (const row of trend) {
      const entry = byPeriod.get(row.period) ?? { period: row.period };
      entry[row.disease_group] = row.case_count;
      byPeriod.set(row.period, entry);
    }
    return Array.from(byPeriod.values()).sort((a, b) =>
      String(a.period).localeCompare(String(b.period)),
    );
  }, [trend]);

  // Pivot year-over-year rows (1 dòng / năm, mỗi nhóm bệnh là 1 cột case_count).
  const yearOverYearChart = useMemo(() => {
    const byYear = new Map<number, Record<string, number>>();
    for (const row of yearOverYear) {
      const entry = byYear.get(row.year) ?? { year: row.year };
      entry[row.disease_group] = row.case_count;
      byYear.set(row.year, entry);
    }
    return Array.from(byYear.values()).sort((a, b) => a.year - b.year);
  }, [yearOverYear]);

  const genderCompareTitle = selectedDisease ? splitDiseaseLabel(selectedDisease, bilingualMap).vi : '-';
  const genderComparisonChart = useMemo(() => {
    if (!genderComparison) return [];
    const otherPercent = Math.max(0, 100 - genderComparison.male_percent - genderComparison.female_percent);
    return [
      { gender: 'Nam', case_count: genderComparison.male_cases, percentage: genderComparison.male_percent, color: '#2563eb' },
      { gender: 'Nữ', case_count: genderComparison.female_cases, percentage: genderComparison.female_percent, color: '#dc2626' },
      { gender: 'Khác/không rõ', case_count: genderComparison.other_cases, percentage: Number(otherPercent.toFixed(1)), color: '#64748b' },
    ].filter((row) => row.case_count > 0);
  }, [genderComparison]);
  const genderTotalTitle =
    genderTotalScope === 'month'
      ? `Tháng ${selectedGenderTotalPeriod}`
      : genderTotalScope === 'year'
        ? `Năm ${selectedGenderTotalYear ?? '-'}`
        : 'Toàn bộ dữ liệu';
  const genderDiseaseTitle =
    genderDiseaseScope === 'month'
      ? `Tháng ${selectedGenderDiseasePeriod}`
      : genderDiseaseScope === 'year'
        ? `Năm ${selectedGenderDiseaseYear ?? '-'}`
        : 'Toàn bộ dữ liệu';
  const showHeaderFilters = mode !== 'gender';
  const showLimit = mode === 'monthly';

  return (
    <div className="space-y-6">
      <section className="relative z-40 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-600 ring-1 ring-blue-100">
              <BarChart3 size={22} />
            </div>
            <div className="min-w-0">
              <h2 className="text-xl font-semibold text-slate-800">{copy.title}</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">{copy.description}</p>
            </div>
          </div>
          <button
            onClick={loadAnalysis}
            disabled={loading || initLoading || !selectedPeriod}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
            Cập nhật
          </button>
        </div>

        {showHeaderFilters && <div className="relative z-50 mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <PeriodCombobox
            label="Tìm tháng/năm phân tích"
            selectedPeriod={selectedPeriod}
            searchPeriod={searchPeriod}
            options={filteredPeriods}
            onSearchChange={setSearchPeriod}
            onSelect={setSelectedPeriod}
          />

          {mode === 'trend' && (
            <div className="md:col-span-2">
              <MultiDiseaseCombobox
                label="Chọn nhóm bệnh (có thể chọn nhiều)"
                selectedDiseases={selectedDiseases}
                searchDisease={searchDisease}
                options={filteredDiseaseOptions}
                bilingualMap={bilingualMap}
                onSearchChange={setSearchDisease}
                onToggle={(value) =>
                  setSelectedDiseases((prev) =>
                    prev.includes(value) ? prev.filter((d) => d !== value) : [...prev, value],
                  )
                }
                onClear={() => setSelectedDiseases([])}
              />
            </div>
          )}

          {showLimit && (
            <label className="space-y-1 text-xs text-slate-500 md:col-start-2 xl:col-start-4">
              <span className="font-medium">Số nhóm hiển thị</span>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {[5, 10, 15, 20, 30].map((n) => (
                  <option key={n} value={n}>
                    Top {n}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>}

        {error && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      </section>

      {mode === 'monthly' && summary && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <StatCard label={`Tổng ca ${summary.period}`} value={summary.total_cases.toLocaleString()} sub={`Mùa: ${summary.season}`} />
          <StatCard label={`So với ${summary.previous_period}`} value={formatPct(summary.change_percent)} sub={summary.trend} />
          <StatCard label="Nhóm bệnh cao nhất" value={summary.top_3_diseases[0]?.case_count.toLocaleString() ?? '-'} sub={summary.top_3_diseases[0]?.disease_group ?? 'Chưa có dữ liệu'} />
          <StatCard label="Dữ liệu phân tích" value="predict_current" sub="Dữ liệu bệnh nhi đã import" />
        </div>
      )}

      {mode === 'monthly' && (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <ChartPanel title={`Top nhóm bệnh trong ${selectedPeriod}`}>
              {topByMonthChart.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={topByMonthChart} layout="vertical" margin={{ left: 12, right: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis type="number" tick={{ fontSize: 12 }} />
                    <YAxis type="category" dataKey="label" width={170} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ca`, 'Số ca']} />
                    <Bar dataKey="case_count" radius={[0, 6, 6, 0]} isAnimationActive={!isMinimalTheme}>
                      {topByMonthChart.map((entry) => <Cell key={entry.disease_group} fill={entry.color} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel title={`Tỷ lệ nhóm bệnh trong ${selectedPeriod}`}>
              {percentChart.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
                <div className="grid grid-cols-1 items-center gap-3 md:grid-cols-2">
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie
                        data={percentChart}
                        dataKey="case_count"
                        nameKey="label"
                        innerRadius={55}
                        outerRadius={95}
                        paddingAngle={2}
                        isAnimationActive={!isMinimalTheme}
                      >
                        {percentChart.map((entry) => <Cell key={entry.disease_group} fill={entry.color} />)}
                      </Pie>
                      <Tooltip formatter={(value: number, _name, item) => {
                        const payload = (item as unknown as { payload: api.DiseasePercentageByMonth & { label: string } }).payload;
                        return [`${value.toLocaleString()} ca (${payload.percentage}%)`, payload.label];
                      }} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="max-h-[260px] space-y-2 overflow-y-auto pr-1 text-xs">
                    {percentChart.map((row) => (
                      <div key={row.disease_group} className="flex items-start gap-2">
                        <span className="mt-0.5 h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: row.color }} />
                        <span className="min-w-0 flex-1"><DiseaseLabelCell raw={row.disease_group} map={bilingualMap} /></span>
                        <span className="font-semibold text-slate-700">{row.percentage}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </ChartPanel>
          </div>

          <ChartPanel title="So sánh tháng này với tháng trước">
            {comparisonChart.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
              <ResponsiveContainer width="100%" height={310}>
                <BarChart data={comparisonChart} margin={{ bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="disease_group" tick={false} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number, name: string) => [`${value.toLocaleString()} ca`, name === 'current_cases' ? selectedPeriod : 'Tháng trước']} />
                  <Legend />
                  <Bar dataKey="previous_cases" name="Tháng trước" fill="#94a3b8" radius={[4, 4, 0, 0]} isAnimationActive={!isMinimalTheme} />
                  <Bar dataKey="current_cases" name={selectedPeriod} fill="#2563eb" radius={[4, 4, 0, 0]} isAnimationActive={!isMinimalTheme} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartPanel>
        </>
      )}

      {mode === 'gender' && (
        <>
          <ChartPanel title="Tổng ca bệnh theo giới tính" subtitle={genderTotalTitle}>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <label className="space-y-1 text-xs text-slate-500">
                <span className="font-medium">Phạm vi thống kê</span>
                <select
                  value={genderTotalScope}
                  onChange={(event) => setGenderTotalScope(event.target.value as GenderScope)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="month">Theo tháng</option>
                  <option value="year">Theo năm</option>
                  <option value="all">Toàn bộ dữ liệu</option>
                </select>
              </label>

              {genderTotalScope === 'month' && (
                <PeriodCombobox
                  label="Tháng thống kê"
                  selectedPeriod={selectedGenderTotalPeriod}
                  searchPeriod={searchGenderTotalPeriod}
                  options={genderTotalPeriodOptions}
                  onSearchChange={setSearchGenderTotalPeriod}
                  onSelect={setSelectedGenderTotalPeriod}
                />
              )}

              {genderTotalScope === 'year' && (
                <label className="space-y-1 text-xs text-slate-500">
                  <span className="font-medium">Năm thống kê</span>
                  <select
                    value={selectedGenderTotalYear ?? ''}
                    onChange={(event) => setSelectedGenderTotalYear(Number(event.target.value))}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {yearOptions.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)]">
              {genderCases.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
                <ResponsiveContainer width="100%" height={270}>
                  <BarChart data={genderCases}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="gender" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ca`, 'Số ca']} />
                    <Bar dataKey="case_count" radius={[6, 6, 0, 0]} isAnimationActive={!isMinimalTheme}>
                      {genderCases.map((row, index) => <Cell key={row.gender} fill={COLORS[index % COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-1">
                {genderCases.map((row, index) => (
                  <div key={row.gender} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                      {row.gender || 'Không rõ'}
                    </div>
                    <div className="mt-3 text-2xl font-bold text-slate-800">{row.case_count.toLocaleString()}</div>
                    <div className="mt-1 text-xs text-slate-500">{row.percentage}% tổng số ca</div>
                  </div>
                ))}
              </div>
            </div>
          </ChartPanel>

          <ChartPanel title="Nhóm bệnh theo giới tính" subtitle={`${genderCompareTitle} · ${genderDiseaseTitle}`}>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_220px_minmax(0,1fr)]">
              <DiseaseCombobox
                label="Nhóm bệnh cần phân tích"
                selectedDisease={selectedDisease}
                searchDisease={searchDisease}
                options={filteredDiseaseOptions}
                bilingualMap={bilingualMap}
                onSearchChange={setSearchDisease}
                onSelect={setSelectedDisease}
              />

              <label className="space-y-1 text-xs text-slate-500">
                <span className="font-medium">Phạm vi phân tích</span>
                <select
                  value={genderDiseaseScope}
                  onChange={(event) => setGenderDiseaseScope(event.target.value as GenderScope)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="month">Theo tháng</option>
                  <option value="year">Theo năm</option>
                  <option value="all">Toàn bộ dữ liệu</option>
                </select>
              </label>

              {genderDiseaseScope === 'month' && (
                <PeriodCombobox
                  label="Tháng phân tích"
                  selectedPeriod={selectedGenderDiseasePeriod}
                  searchPeriod={searchGenderDiseasePeriod}
                  options={genderDiseasePeriodOptions}
                  onSearchChange={setSearchGenderDiseasePeriod}
                  onSelect={setSelectedGenderDiseasePeriod}
                />
              )}

              {genderDiseaseScope === 'year' && (
                <label className="space-y-1 text-xs text-slate-500">
                  <span className="font-medium">Năm phân tích</span>
                  <select
                    value={selectedGenderDiseaseYear ?? ''}
                    onChange={(event) => setSelectedGenderDiseaseYear(Number(event.target.value))}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {yearOptions.map((year) => (
                      <option key={year} value={year}>
                        {year}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
              {genderComparisonChart.length === 0 ? (
                <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu phù hợp" />
              ) : (
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie
                      data={genderComparisonChart}
                      dataKey="case_count"
                      nameKey="gender"
                      innerRadius={55}
                      outerRadius={92}
                      paddingAngle={3}
                      isAnimationActive={!isMinimalTheme}
                    >
                      {genderComparisonChart.map((entry) => <Cell key={entry.gender} fill={entry.color} />)}
                    </Pie>
                    <Tooltip formatter={(value: number, _name, item) => {
                      const payload = (item as unknown as { payload: { gender: string; percentage: number } }).payload;
                      return [`${value.toLocaleString()} ca (${payload.percentage}%)`, payload.gender];
                    }} />
                  </PieChart>
                </ResponsiveContainer>
              )}

              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                {genderComparisonChart.map((row) => (
                  <div key={row.gender} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: row.color }} />
                      {row.gender}
                    </div>
                    <div className="mt-3 text-2xl font-bold text-slate-800">{row.percentage}%</div>
                    <div className="mt-1 text-xs text-slate-500">{row.case_count.toLocaleString()} ca</div>
                  </div>
                ))}
                {genderComparison && (
                  <div className="rounded-xl border border-slate-200 bg-white p-4 md:col-span-3">
                    <div className="text-xs font-medium uppercase text-slate-500">Tổng số ca trong phạm vi đã chọn</div>
                    <div className="mt-2 text-2xl font-bold text-slate-800">{genderComparison.total_cases.toLocaleString()}</div>
                  </div>
                )}
              </div>
            </div>
          </ChartPanel>
        </>
      )}

      {mode === 'trend' && (
        <div className="relative z-0 grid grid-cols-1 gap-6">
          <ChartPanel title="Xu hướng nhóm bệnh đã chọn" subtitle={`${trendSeries.length} nhóm bệnh`}>
            {trendSeries.length === 0 || trendChart.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
              <>
                <TrendSeriesFocusPanel
                  series={trendSeries}
                  highlightedKeys={highlightedTrendDiseases}
                  onToggle={toggleTrendHighlight}
                  onOnly={(key) => setHighlightedTrendDiseases([key])}
                  onClear={() => setHighlightedTrendDiseases([])}
                />
                <ResponsiveContainer width="100%" height={320}>
                <LineChart data={trendChart} margin={{ left: 12, right: 24, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="period" tick={{ fontSize: 12 }} padding={{ left: 24, right: 24 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  {trendSeries.map((s) => {
                    const dimmed = hasTrendHighlight && !highlightedTrendSet.has(s.key);
                    return (
                      <Line
                        key={s.key}
                        type="monotone"
                        dataKey={s.key}
                        name={s.label}
                        stroke={dimmed ? '#cbd5e1' : s.color}
                        strokeOpacity={dimmed ? 0.42 : 1}
                        strokeWidth={dimmed ? 1.6 : 3}
                        dot={(props) => (
                          <TrendPointDot
                            {...props}
                            dataKey={s.key}
                            color={s.color}
                            dimmed={dimmed}
                            setHoverPoint={setHoveredTrendPoint}
                          />
                        )}
                        activeDot={false}
                        connectNulls
                        isAnimationActive={!isMinimalTheme}
                      />
                    );
                  })}
                </LineChart>
              </ResponsiveContainer>
                <TrendLineTooltip hoverPoint={hoveredTrendPoint} series={trendSeries} chartData={trendChart} />
              </>
            )}
          </ChartPanel>

          <ChartPanel title="So sánh cùng tháng qua các năm" subtitle={selectedPeriodInfo ? monthLabel(selectedPeriodInfo.month) : ''}>
            {trendSeries.length === 0 || yearOverYearChart.length === 0 ? <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu" /> : (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={yearOverYearChart} barGap={2} margin={{ bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(value: number, name: string) => [`${value.toLocaleString()} ca`, name]} />
                  <Legend />
                  {trendSeries.map((s) => (
                    <Bar
                      key={s.key}
                      dataKey={s.key}
                      name={s.label}
                      fill={s.color}
                      stackId="selected-diseases"
                      isAnimationActive={!isMinimalTheme}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartPanel>
        </div>
      )}
    </div>
  );
}

function TrendSeriesFocusPanel({
  series,
  highlightedKeys,
  onToggle,
  onOnly,
  onClear,
}: {
  series: Array<{ key: string; label: string; color: string }>;
  highlightedKeys: string[];
  onToggle: (key: string) => void;
  onOnly: (key: string) => void;
  onClear: () => void;
}) {
  const highlightedSet = new Set(highlightedKeys);
  const hasHighlight = highlightedKeys.length > 0;

  return (
    <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-800">Làm rõ đường biểu đồ</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {hasHighlight
              ? `${highlightedKeys.length} nhóm bệnh đang giữ màu, các nhóm còn lại được làm mờ.`
              : 'Chưa chọn nhóm nào, tất cả đường đang hiển thị bình thường.'}
          </div>
        </div>
        <button
          type="button"
          onClick={onClear}
          disabled={!hasHighlight}
          className="inline-flex shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-45"
        >
          Hiện tất cả
        </button>
      </div>

      <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
        {series.map((item) => {
          const active = highlightedSet.has(item.key);
          const dimmed = hasHighlight && !active;
          return (
            <div
              key={item.key}
              className={`flex items-start gap-2 rounded-lg border bg-white px-2.5 py-2 transition ${
                active
                  ? 'border-blue-300 ring-2 ring-blue-100'
                  : dimmed
                    ? 'border-slate-200 opacity-65'
                    : 'border-slate-200 hover:border-blue-200'
              }`}
            >
              <button
                type="button"
                onClick={() => onToggle(item.key)}
                aria-pressed={active}
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border ${
                  active
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-300 bg-white text-transparent hover:border-blue-400'
                }`}
                title={active ? 'Bỏ làm nổi bật' : 'Làm nổi bật nhóm bệnh này'}
              >
                <Check size={13} />
              </button>
              <button
                type="button"
                onClick={() => onToggle(item.key)}
                className="min-w-0 flex-1 text-left"
              >
                <span className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: dimmed ? '#cbd5e1' : item.color }}
                  />
                  <span className={`line-clamp-2 text-xs font-medium leading-5 ${dimmed ? 'text-slate-400' : 'text-slate-700'}`}>
                    {item.label}
                  </span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => onOnly(item.key)}
                className="shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold text-blue-600 hover:bg-blue-50"
              >
                Chỉ xem
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PeriodCombobox({
  label,
  selectedPeriod,
  searchPeriod,
  options,
  onSearchChange,
  onSelect,
}: {
  label: string;
  selectedPeriod: string;
  searchPeriod: string;
  options: api.DashboardPeriodOption[];
  onSearchChange: (value: string) => void;
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((p) => p.period === selectedPeriod);
  const selectedLabel = selected ? `${selected.period} · ${selected.season}` : selectedPeriod;

  return (
    <label className="block space-y-1 text-xs text-slate-500">
      <span className="font-medium">{label}</span>
      <div
        ref={wrapperRef}
        className="relative"
        onBlur={(event) => {
          if (!wrapperRef.current?.contains(event.relatedTarget as Node | null)) {
            setOpen(false);
            onSearchChange('');
          }
        }}
      >
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-slate-400" />
        <input
          value={open ? searchPeriod : selectedLabel}
          onFocus={() => {
            setOpen(true);
            onSearchChange('');
          }}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            onSearchChange(event.target.value);
            setOpen(true);
          }}
          placeholder="Gõ năm hoặc tháng..."
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <ChevronDown
          size={17}
          className={`pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />

        {open && (
          <div className="absolute left-0 right-0 top-full z-[1000] mt-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
            {options.length === 0 ? (
              <div className="px-3 py-3 text-sm text-slate-400">Không tìm thấy tháng/năm phù hợp</div>
            ) : (
              options.map((option) => {
                const active = option.period === selectedPeriod;
                return (
                  <button
                    key={option.period}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      onSelect(option.period);
                      onSearchChange('');
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      active ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="h-5 w-5 shrink-0">{active && <Check size={16} className="text-blue-600" />}</span>
                    <span className="min-w-0 flex-1">{option.period} · {option.season}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>
    </label>
  );
}

function DiseaseCombobox({
  label,
  selectedDisease,
  searchDisease,
  options,
  bilingualMap,
  onSearchChange,
  onSelect,
}: {
  label: string;
  selectedDisease: string;
  searchDisease: string;
  options: api.DashboardDiseaseGroupOption[];
  bilingualMap: Record<string, string>;
  onSearchChange: (value: string) => void;
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selectedLabel = selectedDisease ? splitDiseaseLabel(selectedDisease, bilingualMap).vi : '';

  return (
    <label className="block space-y-1 text-xs text-slate-500">
      <span className="font-medium">{label}</span>
      <div
        ref={wrapperRef}
        className="relative"
        onBlur={(event) => {
          if (!wrapperRef.current?.contains(event.relatedTarget as Node | null)) {
            setOpen(false);
            onSearchChange('');
          }
        }}
      >
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-slate-400" />
        <input
          value={open ? searchDisease : selectedLabel}
          onFocus={() => {
            setOpen(true);
            onSearchChange('');
          }}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            onSearchChange(event.target.value);
            setOpen(true);
          }}
          placeholder="Tìm và chọn nhóm bệnh..."
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <ChevronDown
          size={17}
          className={`pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />

        {open && (
          <div className="absolute left-0 right-0 top-full z-[1000] mt-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
            {options.length === 0 ? (
              <div className="px-3 py-3 text-sm text-slate-400">Không tìm thấy nhóm bệnh phù hợp</div>
            ) : (
              options.map((option) => {
                const optionLabel = splitDiseaseLabel(option.disease_group, bilingualMap).vi;
                const active = option.disease_group === selectedDisease;
                return (
                  <button
                    key={option.disease_group}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      onSelect(option.disease_group);
                      onSearchChange('');
                      setOpen(false);
                    }}
                    className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      active ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="mt-0.5 h-5 w-5 shrink-0">
                      {active && <Check size={16} className="text-blue-600" />}
                    </span>
                    <span className="min-w-0 flex-1 leading-5">{optionLabel}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>
    </label>
  );
}

function MultiDiseaseCombobox({
  label,
  selectedDiseases,
  searchDisease,
  options,
  bilingualMap,
  onSearchChange,
  onToggle,
  onClear,
}: {
  label: string;
  selectedDiseases: string[];
  searchDisease: string;
  options: api.DashboardDiseaseGroupOption[];
  bilingualMap: Record<string, string>;
  onSearchChange: (value: string) => void;
  onToggle: (value: string) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selectedSet = new Set(selectedDiseases);

  return (
    <label className="block space-y-1 text-xs text-slate-500">
      <span className="font-medium">{label}</span>
      <div
        ref={wrapperRef}
        className="relative"
        onBlur={(event) => {
          if (!wrapperRef.current?.contains(event.relatedTarget as Node | null)) {
            setOpen(false);
            onSearchChange('');
          }
        }}
      >
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-slate-400" />
        <input
          value={searchDisease}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            onSearchChange(event.target.value);
            setOpen(true);
          }}
          placeholder={
            selectedDiseases.length > 0 ? `Đã chọn ${selectedDiseases.length} nhóm bệnh...` : 'Tìm và chọn nhóm bệnh...'
          }
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-10 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <ChevronDown
          size={17}
          className={`pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />

        {open && (
          <div className="absolute left-0 right-0 top-full z-[1000] mt-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
            {selectedDiseases.length > 0 && (
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={onClear}
                className="mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-rose-600 hover:bg-rose-50"
              >
                Bỏ chọn tất cả ({selectedDiseases.length})
              </button>
            )}
            {options.length === 0 ? (
              <div className="px-3 py-3 text-sm text-slate-400">Không tìm thấy nhóm bệnh phù hợp</div>
            ) : (
              options.map((option) => {
                const optionLabel = splitDiseaseLabel(option.disease_group, bilingualMap).vi;
                const active = selectedSet.has(option.disease_group);
                return (
                  <button
                    key={option.disease_group}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => onToggle(option.disease_group)}
                    className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      active ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border ${
                        active ? 'border-blue-600 bg-blue-600' : 'border-slate-300 bg-white'
                      }`}
                    >
                      {active && <Check size={14} className="text-white" />}
                    </span>
                    <span className="min-w-0 flex-1 leading-5">{optionLabel}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {selectedDiseases.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {selectedDiseases.map((dg, idx) => (
            <span
              key={dg}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 py-1 pl-2 pr-1 text-xs text-slate-700"
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
              <span className="max-w-[180px] truncate">{splitDiseaseLabel(dg, bilingualMap).vi}</span>
              <button
                type="button"
                onClick={() => onToggle(dg)}
                className="flex h-4 w-4 items-center justify-center rounded-full text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                aria-label="Bỏ chọn"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </label>
  );
}

function ChartPanel({
  title,
  subtitle,
  children,
  className = '',
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      <div className="mb-3">
        <div className="font-semibold text-slate-800">{title}</div>
        {subtitle && <div className="mt-1 text-xs text-slate-500">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
        <Activity size={16} className="text-blue-600" />
      </div>
      <div className="break-words text-2xl font-bold text-slate-800">{value}</div>
      <div className="mt-1 line-clamp-2 break-words text-xs text-slate-400">{sub}</div>
    </div>
  );
}
