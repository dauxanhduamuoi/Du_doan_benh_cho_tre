import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Calendar, TrendingUp, AlertTriangle, Loader2, RefreshCcw, Search } from 'lucide-react';
import * as api from '@/lib/api';
import { useT } from '@/lib/i18n';
import { ensureBilingualMap, splitDiseaseLabel } from '@/lib/disease';
import DiseaseLabelCell from './common/DiseaseLabelCell';
import { useMinimalTheme } from '@/lib/useMinimalTheme';

type Season = 'dry' | 'rainy';

const SEASONS: Season[] = ['dry', 'rainy'];

// Đúng với backend và khí hậu miền Nam/TP.HCM:
// Mùa khô: tháng 12, 1, 2, 3, 4. Mùa mưa: tháng 5-11.
const SEASON_BY_MONTH: Record<number, Season> = {
  1: 'dry',
  2: 'dry',
  3: 'dry',
  4: 'dry',
  5: 'rainy',
  6: 'rainy',
  7: 'rainy',
  8: 'rainy',
  9: 'rainy',
  10: 'rainy',
  11: 'rainy',
  12: 'dry',
};

const DISEASE_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#6366f1', '#14b8a6', '#f43f5e', '#8b5cf6'];
const SEASON_COLORS: Record<Season, string> = {
  dry: '#f59e0b',
  rainy: '#0ea5e9',
};

function parsePeriod(p: string): { year: number; month: number } {
  const [y, m] = p.split('-');
  return { year: parseInt(y, 10), month: parseInt(m, 10) };
}

function monthLabel(month: number): string {
  return `T${month}`;
}

function backendSeasonLabel(season: Season): string {
  return season === 'dry' ? 'Mùa khô' : 'Mùa mưa';
}

function EmptyChart({ loading, label, t }: { loading: boolean; label: string; t: (k: string) => string }) {
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

function chunkText(text: string, maxChars: number): string[] {
  if (!text) return [];
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let cur = '';
  for (const w of words) {
    const candidate = cur ? `${cur} ${w}` : w;
    if (candidate.length <= maxChars) {
      cur = candidate;
    } else {
      if (cur) lines.push(cur);
      cur = w;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

function normalizeSearchText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('vi')
    .trim();
}

function matchesDiseaseGroup(raw: string, query: string, bilingualMap: Record<string, string>): boolean {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) return true;
  const label = splitDiseaseLabel(raw, bilingualMap);
  return normalizeSearchText(`${raw} ${label.vi} ${label.en ?? ''}`).includes(normalizedQuery);
}

function SeasonalBilingualLegend({
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
            <span className="inline-block w-3 h-3 mt-0.5 rounded-sm shrink-0" style={{ backgroundColor: entry.color }} />
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

export default function SeasonalAnalysis() {
  const isMinimalTheme = useMinimalTheme();
  const t = useT();
  const [data, setData] = useState<api.MonthlyStat[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [selectedSeason, setSelectedSeason] = useState<Season>('rainy');
  const [seasonalLimit, setSeasonalLimit] = useState(10);
  const [seasonalSummary, setSeasonalSummary] = useState<api.SeasonalSummaryRow[]>([]);
  const [seasonCompare, setSeasonCompare] = useState<api.DiseaseSeasonComparisonRow[]>([]);
  const [seasonPeak, setSeasonPeak] = useState<api.SeasonalPeakRow[]>([]);
  const [bilingualMap, setBilingualMap] = useState<Record<string, string>>({});
  const [seasonSummarySearch, setSeasonSummarySearch] = useState('');
  const [seasonCompareSearch, setSeasonCompareSearch] = useState('');
  const [seasonPeakSearch, setSeasonPeakSearch] = useState('');

  const seasonLabel = useCallback((s: Season) => t(`season.${s}`), [t]);

  useEffect(() => {
    ensureBilingualMap().then(setBilingualMap).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Dashboard backend phân tích nguồn predict_current. Gọi predict_current để frontend rõ nghĩa.
      const [rows, summaryRows, compareRows, peakRows] = await Promise.all([
        api.getMonthlyStatistics('predict_current'),
        api.getSeasonalSummary(backendSeasonLabel(selectedSeason), seasonalLimit),
        api.getDiseaseSeasonComparison(undefined, seasonalLimit),
        api.getSeasonalPeak(seasonalLimit),
      ]);
      setData(rows);
      setSeasonalSummary(summaryRows);
      setSeasonCompare(compareRows);
      setSeasonPeak(peakRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedSeason, seasonalLimit]);

  useEffect(() => {
    load();
  }, [load]);

  const years = useMemo(() => {
    const ys = new Set<number>();
    for (const r of data) ys.add(parsePeriod(r.period).year);
    return Array.from(ys).sort((a, b) => a - b);
  }, [data]);

  useEffect(() => {
    if (years.length > 0 && (selectedYear === null || !years.includes(selectedYear))) {
      setSelectedYear(years[years.length - 1]);
    }
  }, [years, selectedYear]);

  const topDiseases = useMemo(() => {
    const sum = new Map<string, number>();
    for (const r of data) sum.set(r.disease_group, (sum.get(r.disease_group) ?? 0) + r.case_count);
    return Array.from(sum.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([name]) => name);
  }, [data]);

  const monthlyChartData = useMemo(() => {
    if (selectedYear === null) return [];
    const rows: Array<Record<string, number | string>> = Array.from({ length: 12 }, (_, i) => {
      const m = i + 1;
      const row: Record<string, number | string> = {
        month: monthLabel(m),
        season: seasonLabel(SEASON_BY_MONTH[m]),
      };
      for (const d of topDiseases) row[d] = 0;
      return row;
    });

    for (const r of data) {
      const { year, month } = parsePeriod(r.period);
      if (year !== selectedYear) continue;
      if (!topDiseases.includes(r.disease_group)) continue;
      const row = rows[month - 1];
      row[r.disease_group] = (row[r.disease_group] as number) + r.case_count;
    }

    return rows;
  }, [data, selectedYear, topDiseases, seasonLabel]);

  const seasonDiseaseData = useMemo(() => {
    const byDisease = new Map<string, Record<string, number | string>>();
    for (const disease of topDiseases) {
      byDisease.set(disease, {
        disease,
        [seasonLabel('dry')]: 0,
        [seasonLabel('rainy')]: 0,
      });
    }

    for (const r of data) {
      if (!topDiseases.includes(r.disease_group)) continue;
      const { month } = parsePeriod(r.period);
      const season = seasonLabel(SEASON_BY_MONTH[month]);
      const row = byDisease.get(r.disease_group);
      if (!row) continue;
      row[season] = (row[season] as number) + r.case_count;
    }

    return Array.from(byDisease.values());
  }, [data, topDiseases, seasonLabel]);

  const comparativeData = useMemo(() => {
    const rows = SEASONS.map((s) => {
      const row: Record<string, number | string> = { season: seasonLabel(s) };
      for (const y of years) row[String(y)] = 0;
      return row;
    });
    const rowBySeason = new Map<string, Record<string, number | string>>();
    rows.forEach((r) => rowBySeason.set(r.season as string, r));

    for (const r of data) {
      const { year, month } = parsePeriod(r.period);
      const season = seasonLabel(SEASON_BY_MONTH[month]);
      const row = rowBySeason.get(season);
      if (!row) continue;
      row[String(year)] = (row[String(year)] as number) + r.case_count;
    }

    return rows;
  }, [data, years, seasonLabel]);

  const insights = useMemo(() => {
    if (data.length === 0 || selectedYear === null) return null;

    const byMonth = new Map<number, number>();
    for (const r of data) {
      const { year, month } = parsePeriod(r.period);
      if (year !== selectedYear) continue;
      byMonth.set(month, (byMonth.get(month) ?? 0) + r.case_count);
    }
    if (byMonth.size === 0) return null;

    const [peakMonth, peakCases] = Array.from(byMonth.entries()).sort((a, b) => b[1] - a[1])[0];
    const peakSeason = SEASON_BY_MONTH[peakMonth];

    const sumSeasonYear = (year: number, season: Season) => {
      let total = 0;
      for (const r of data) {
        const { year: yr, month } = parsePeriod(r.period);
        if (yr === year && SEASON_BY_MONTH[month] === season) total += r.case_count;
      }
      return total;
    };

    const curr = sumSeasonYear(selectedYear, selectedSeason);
    const prev = sumSeasonYear(selectedYear - 1, selectedSeason);
    let deltaLabel = t('seasonal.noPrevYear');
    if (prev > 0) {
      const pct = ((curr - prev) / prev) * 100;
      deltaLabel = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
    } else if (curr > 0) {
      deltaLabel = t('seasonal.mewlySeason');
    }

    return {
      peakMonth,
      peakSeason,
      peakCases,
      deltaLabel,
      currSeasonCases: curr,
    };
  }, [data, selectedYear, selectedSeason, t]);

  const seasonTopDiseases = useMemo(() => {
    const sum = new Map<string, number>();
    for (const r of data) {
      const { month } = parsePeriod(r.period);
      if (SEASON_BY_MONTH[month] !== selectedSeason) continue;
      sum.set(r.disease_group, (sum.get(r.disease_group) ?? 0) + r.case_count);
    }
    return Array.from(sum.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
  }, [data, selectedSeason]);

  const filteredSeasonalSummary = useMemo(
    () => seasonalSummary.filter((row) => matchesDiseaseGroup(row.disease_group, seasonSummarySearch, bilingualMap)),
    [seasonalSummary, seasonSummarySearch, bilingualMap],
  );

  const filteredSeasonCompare = useMemo(
    () => seasonCompare.filter((row) => matchesDiseaseGroup(row.disease_group, seasonCompareSearch, bilingualMap)),
    [seasonCompare, seasonCompareSearch, bilingualMap],
  );

  const filteredSeasonPeak = useMemo(
    () => seasonPeak.filter((row) => matchesDiseaseGroup(row.disease_group, seasonPeakSearch, bilingualMap)),
    [seasonPeak, seasonPeakSearch, bilingualMap],
  );

  const empty = data.length === 0;

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex items-center gap-2">
            <Calendar size={20} className="text-slate-500" />
            <span className="text-sm font-medium text-slate-700">{t('seasonal.filters')}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">{t('seasonal.peakSeason')}:</span>
            <select
              value={selectedSeason}
              onChange={(e) => setSelectedSeason(e.target.value as Season)}
              className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {SEASONS.map((season) => (
                <option key={season} value={season}>
                  {seasonLabel(season)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">{t('reports.col.year')}:</span>
            {years.length === 0 ? (
              <span className="text-sm text-slate-400 italic">{t('seasonal.noYear')}</span>
            ) : (
              <select
                value={selectedYear ?? ''}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            )}
          </div>
          <label className="flex items-center gap-2">
            <span className="text-sm text-slate-500">Số nhóm:</span>
            <select
              value={seasonalLimit}
              onChange={(e) => setSeasonalLimit(Number(e.target.value))}
              className="px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {[5, 10, 15, 20, 30].map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="ml-auto inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
            {t('common.refresh')}
          </button>
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm">{error}</div>}

      {empty && !loading && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-3 text-sm">
          {t('seasonal.noHistory')}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="seasonal-highlight-card seasonal-highlight-peak bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl p-6 text-white shadow-md">
          <div className="flex items-start justify-between mb-4">
            <TrendingUp size={24} className="seasonal-highlight-icon" />
            <span className="seasonal-highlight-badge text-xs bg-white/20 px-2 py-1 rounded">{t('seasonal.peak')}</span>
          </div>
          <h3 className="text-2xl font-bold mb-1">
            {insights
              ? `${t('seasonal.peakMonth')} ${insights.peakMonth} · ${t('seasonal.peakSeason')} ${seasonLabel(insights.peakSeason)}`
              : '—'}
          </h3>
          <p className="seasonal-highlight-muted text-blue-100 text-sm">
            {insights ? `${insights.peakCases.toLocaleString()} ${t('seasonal.casesHighest')} ${selectedYear}` : t('seasonal.noDataYet')}
          </p>
        </div>

        <div className="seasonal-highlight-card seasonal-highlight-compare bg-gradient-to-br from-orange-500 to-orange-600 rounded-xl p-6 text-white shadow-md">
          <div className="flex items-start justify-between mb-4">
            <AlertTriangle size={24} className="seasonal-highlight-icon" />
            <span className="seasonal-highlight-badge text-xs bg-white/20 px-2 py-1 rounded">{t('seasonal.compare')}</span>
          </div>
          <h3 className="text-2xl font-bold mb-1">{insights?.deltaLabel ?? '—'}</h3>
          <p className="seasonal-highlight-muted text-orange-100 text-sm">
            {seasonLabel(selectedSeason)} {selectedYear} {t('seasonal.versus')} {selectedYear ? selectedYear - 1 : ''}
          </p>
        </div>

        <div className="seasonal-highlight-card seasonal-highlight-total bg-gradient-to-br from-purple-500 to-purple-600 rounded-xl p-6 text-white shadow-md">
          <div className="flex items-start justify-between mb-4">
            <Calendar size={24} className="seasonal-highlight-icon" />
            <span className="seasonal-highlight-badge text-xs bg-white/20 px-2 py-1 rounded">{t('seasonal.sumLabel')}</span>
          </div>
          <h3 className="text-2xl font-bold mb-1">{insights ? insights.currSeasonCases.toLocaleString() : '—'}</h3>
          <p className="seasonal-highlight-muted text-purple-100 text-sm">
            {t('seasonal.inSeason')} {seasonLabel(selectedSeason)} {selectedYear ?? ''}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-800 mb-4">
            {t('seasonal.monthlyTrend')} ({selectedYear ?? '—'})
          </h3>
          {monthlyChartData.length === 0 || topDiseases.length === 0 ? (
            <EmptyChart loading={loading} label={t('seasonal.noYearData')} t={t} />
          ) : (
            <ResponsiveContainer width="100%" height={400}>
              <AreaChart data={monthlyChartData} margin={{ bottom: 60 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis />
                <Tooltip
                  contentStyle={{ borderRadius: '0.75rem', border: '1px solid #e2e8f0' }}
                  formatter={(value: number, name: string) => {
                    const lbl = splitDiseaseLabel(name, bilingualMap);
                    return [Number(value).toLocaleString(), lbl.en ? `${lbl.vi} / ${lbl.en}` : lbl.vi];
                  }}
                  labelFormatter={(label, payload) => {
                    const item = payload?.[0]?.payload as { season?: string } | undefined;
                    return item?.season ? `${label} · ${item.season}` : String(label);
                  }}
                />
                <Legend
                  verticalAlign="bottom"
                  content={(props) => (
                    <SeasonalBilingualLegend
                      payload={props.payload as unknown as Array<{ value: string; color: string }>}
                      bilingualMap={bilingualMap}
                    />
                  )}
                />
                {topDiseases.map((d, i) => (
                  <Area
                    key={d}
                    type="monotone"
                    dataKey={d}
                    stackId="1"
                    stroke={DISEASE_COLORS[i % DISEASE_COLORS.length]}
                    fill={DISEASE_COLORS[i % DISEASE_COLORS.length]}
                    name={d}
                    isAnimationActive={!isMinimalTheme}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-800 mb-4">{t('seasonal.distribution')}</h3>
          {seasonDiseaseData.length === 0 ? (
            <EmptyChart loading={loading} label={t('common.noData')} t={t} />
          ) : (
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={seasonDiseaseData} layout="vertical" margin={{ left: 140, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis
                  type="category"
                  dataKey="disease"
                  width={130}
                  tick={(props) => {
                    const { x, y, payload } = props as unknown as { x: number; y: number; payload: { value: string } };
                    const lbl = splitDiseaseLabel(payload.value, bilingualMap);
                    const lines = chunkText(lbl.vi, 18).slice(0, 2);
                    return (
                      <text x={x} y={y} textAnchor="end" fill="#475569" fontSize={11}>
                        {lines.map((line, i) => (
                          <tspan key={i} x={x} dy={i === 0 ? 0 : '1.2em'}>
                            {line}
                          </tspan>
                        ))}
                      </text>
                    );
                  }}
                />
                <Tooltip formatter={(value: number) => Number(value).toLocaleString()} />
                <Legend />
                <Bar dataKey={seasonLabel('dry')} name={seasonLabel('dry')} fill={SEASON_COLORS.dry} isAnimationActive={!isMinimalTheme} />
                <Bar dataKey={seasonLabel('rainy')} name={seasonLabel('rainy')} fill={SEASON_COLORS.rainy} isAnimationActive={!isMinimalTheme} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-800 mb-4">{t('seasonal.comparison')}</h3>
        {years.length === 0 ? (
          <EmptyChart loading={loading} label={t('common.noData')} t={t} />
        ) : (
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={comparativeData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="season" />
              <YAxis />
              <Tooltip formatter={(value: number) => Number(value).toLocaleString()} />
              <Legend />
              {years.map((y, i) => (
                <Bar
                  key={y}
                  dataKey={String(y)}
                  fill={DISEASE_COLORS[i % DISEASE_COLORS.length]}
                  name={String(y)}
                  isAnimationActive={!isMinimalTheme}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-800 mb-4">
          {t('seasonal.topOfSeason')} {seasonLabel(selectedSeason)} {t('seasonal.historyTotal')}
        </h3>
        {seasonTopDiseases.length === 0 ? (
          <p className="text-sm text-slate-500">{t('seasonal.noSeasonData')}</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {seasonTopDiseases.map(([disease, cases], i) => {
              const color = DISEASE_COLORS[i % DISEASE_COLORS.length];
              const lbl = splitDiseaseLabel(disease, bilingualMap);
              return (
                <div key={disease} className="p-4 rounded-lg border border-slate-200 bg-slate-50">
                  <div className="flex items-start gap-2 mb-2">
                    <span className="w-2.5 h-2.5 rounded-full mt-1 shrink-0" style={{ backgroundColor: color }} />
                    <div className="min-w-0 leading-tight">
                      <div className="font-medium text-slate-800" title={lbl.vi}>
                        {lbl.vi}
                      </div>
                      {lbl.en && (
                        <div className="text-[11px] italic text-slate-500" title={lbl.en}>
                          {lbl.en}
                        </div>
                      )}
                    </div>
                  </div>
                  <p className="text-2xl font-bold text-slate-700">{cases.toLocaleString()}</p>
                  <p className="text-xs text-slate-500">
                    {t('seasonal.inSeason')} {seasonLabel(selectedSeason)}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <h3 className="text-lg font-semibold text-slate-800">Phân tích mùa vụ chi tiết</h3>
          <p className="mt-1 text-sm text-slate-500">
            Các bảng này dùng trực tiếp API mùa vụ: seasonal-summary, disease-season-comparison và seasonal-peak.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <SeasonPanel title={`Nhóm bệnh nổi bật trong ${seasonLabel(selectedSeason)}`}>
            <SeasonSearchInput value={seasonSummarySearch} onChange={setSeasonSummarySearch} />
            <SeasonDataTable
              empty={filteredSeasonalSummary.length === 0}
              loading={loading}
              headers={['Nhóm bệnh', 'Số ca']}
              rows={filteredSeasonalSummary.map((row) => [
                <DiseaseLabelCell key="dg" raw={row.disease_group} map={bilingualMap} />,
                row.case_count.toLocaleString(),
              ])}
            />
          </SeasonPanel>

          <SeasonPanel title="Mùa chiếm ưu thế theo nhóm bệnh">
            <SeasonSearchInput value={seasonCompareSearch} onChange={setSeasonCompareSearch} />
            <SeasonDataTable
              empty={filteredSeasonCompare.length === 0}
              loading={loading}
              headers={['Nhóm bệnh', 'Mùa trội', 'Mùa khô', 'Mùa mưa', 'Tổng']}
              rows={filteredSeasonCompare.map((row) => [
                <DiseaseLabelCell key="dg" raw={row.disease_group} map={bilingualMap} />,
                row.dominant_season,
                row.dry_season_cases.toLocaleString(),
                row.rainy_season_cases.toLocaleString(),
                row.total_cases.toLocaleString(),
              ])}
            />
          </SeasonPanel>
        </div>

        <SeasonPanel title="Tháng đỉnh theo nhóm bệnh">
          <SeasonSearchInput value={seasonPeakSearch} onChange={setSeasonPeakSearch} />
          <SeasonDataTable
            empty={filteredSeasonPeak.length === 0}
            loading={loading}
            headers={['Nhóm bệnh', 'Tháng đỉnh', 'Mùa', 'Trung bình ca']}
            rows={filteredSeasonPeak.map((row) => [
              <DiseaseLabelCell key="dg" raw={row.disease_group} map={bilingualMap} />,
              row.peak_month,
              row.season,
              row.avg_cases.toLocaleString(),
            ])}
          />
        </SeasonPanel>
      </section>
    </div>
  );
}

function SeasonPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <h4 className="mb-3 font-semibold text-slate-800">{title}</h4>
      {children}
    </div>
  );
}

function SeasonSearchInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="relative mb-3 block max-w-md">
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Tìm nhóm bệnh..."
        aria-label="Tìm kiếm nhóm bệnh"
        className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
      />
    </label>
  );
}

function SeasonDataTable({
  headers,
  rows,
  empty,
  loading,
}: {
  headers: string[];
  rows: Array<Array<ReactNode>>;
  empty: boolean;
  loading: boolean;
}) {
  if (empty) return <EmptyChart loading={loading} label="Chưa có dữ liệu" t={(key) => key} />;

  return (
    <div className="max-h-[360px] overflow-auto">
      <table className="w-full min-w-[680px] text-xs">
        <thead className="sticky top-0 z-10 bg-white">
          <tr className="border-b border-slate-200 text-left text-slate-500">
            {headers.map((header, idx) => (
              <th key={header} className={`py-2 pr-3 ${idx > 1 ? 'text-right' : ''}`}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIdx) => (
            <tr key={rowIdx} className="border-b border-slate-100 align-top last:border-0">
              {row.map((cell, idx) => (
                <td key={idx} className={`py-2 pr-3 ${idx > 1 ? 'text-right font-semibold text-slate-700' : ''}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
