import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  Calendar,
  Loader2,
  RefreshCcw,
  SlidersHorizontal,
  Users,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import * as api from '@/lib/api';
import DiseaseLabelCell from './common/DiseaseLabelCell';
import { ensureBilingualMap, splitDiseaseLabel } from '@/lib/disease';

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
  '#db2777',
];

function toNumberOrUndefined(value: string): number | undefined {
  if (value.trim() === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function EmptyBox({ loading, label }: { loading: boolean; label: string }) {
  return (
    <div className="flex h-[280px] items-center justify-center text-sm text-slate-400">
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

export default function AgeAnalysis() {
  const [periods, setPeriods] = useState<api.DashboardPeriodOption[]>([]);
  const [period, setPeriod] = useState('');
  const [minAge, setMinAge] = useState('');
  const [maxAge, setMaxAge] = useState('');
  const [limit, setLimit] = useState(10);
  const [total, setTotal] = useState<api.CasesByAgeRangeResult | null>(null);
  const [rows, setRows] = useState<api.DiseaseByAgeRangeRow[]>([]);
  const [bilingualMap, setBilingualMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [initLoading, setInitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ensureBilingualMap().then(setBilingualMap).catch(() => undefined);
  }, []);

  useEffect(() => {
    let alive = true;
    setInitLoading(true);
    api
      .getDashboardPeriods()
      .then((data) => {
        if (alive) setPeriods(data);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        if (alive) setInitLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const ageRangeLabel = `${minAge || '0'} - ${maxAge || 'không giới hạn'} tháng tuổi`;
  const periodLabel = period || 'Toàn bộ thời gian';

  const chartRows = useMemo(
    () =>
      rows.slice(0, 10).map((row, index) => ({
        ...row,
        label: splitDiseaseLabel(row.disease_group, bilingualMap).vi,
        color: COLORS[index % COLORS.length],
      })),
    [rows, bilingualMap],
  );

  const load = useCallback(async () => {
    const minMonthAge = toNumberOrUndefined(minAge);
    const maxMonthAge = toNumberOrUndefined(maxAge);

    if (minMonthAge !== undefined && minMonthAge < 0) {
      setError('Tháng tuổi bắt đầu không được nhỏ hơn 0.');
      return;
    }
    if (maxMonthAge !== undefined && maxMonthAge < 0) {
      setError('Tháng tuổi kết thúc không được nhỏ hơn 0.');
      return;
    }
    if (minMonthAge !== undefined && maxMonthAge !== undefined && maxMonthAge < minMonthAge) {
      setError('Tháng tuổi kết thúc phải lớn hơn hoặc bằng tháng tuổi bắt đầu.');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const params = {
        period: period || undefined,
        minMonthAge,
        maxMonthAge,
      };
      const [totalResult, diseaseRows] = await Promise.all([
        api.getCasesByAgeRange(params),
        api.getDiseaseByAgeRange({ ...params, limit }),
      ]);
      setTotal(totalResult);
      setRows(diseaseRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [period, minAge, maxAge, limit]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-600 ring-1 ring-blue-100">
              <SlidersHorizontal size={22} />
            </div>
            <div className="min-w-0">
              <h2 className="text-xl font-semibold text-slate-800">Phân tích độ tuổi</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                Thống kê nhóm bệnh theo khoảng tháng tuổi và thời điểm ghi nhận trong dữ liệu bệnh nhi đã import.
              </p>
            </div>
          </div>

          <button
            onClick={load}
            disabled={loading || initLoading}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
            Cập nhật
          </button>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-1 text-xs text-slate-500">
            <span className="font-medium">Thời điểm</span>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Toàn bộ thời gian</option>
              {periods.map((p) => (
                <option key={p.period} value={p.period}>
                  {p.period} · {p.season}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-xs text-slate-500">
            <span className="font-medium">Từ tháng tuổi</span>
            <input
              value={minAge}
              onChange={(e) => setMinAge(e.target.value)}
              inputMode="numeric"
              placeholder="Ví dụ: 0"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>

          <label className="space-y-1 text-xs text-slate-500">
            <span className="font-medium">Đến tháng tuổi</span>
            <input
              value={maxAge}
              onChange={(e) => setMaxAge(e.target.value)}
              inputMode="numeric"
              placeholder="Ví dụ: 12"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>

          <label className="space-y-1 text-xs text-slate-500">
            <span className="font-medium">Số nhóm bệnh</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {[5, 10, 15, 20, 30, 50].map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      </section>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard icon={Users} label="Số ca trong khoảng tuổi" value={total?.total_cases.toLocaleString() ?? '—'} sub={ageRangeLabel} />
        <StatCard icon={Calendar} label="Thời điểm" value={periodLabel} sub={period ? 'Một tháng được chọn' : 'Tính trên toàn bộ dữ liệu'} />
        <StatCard icon={Activity} label="Nhóm bệnh có dữ liệu" value={rows.length.toLocaleString()} sub={`Đang hiển thị Top ${limit}`} />
        <StatCard
          icon={BarChart3}
          label="Nhóm bệnh cao nhất"
          value={rows[0]?.case_count.toLocaleString() ?? '—'}
          sub={rows[0] ? splitDiseaseLabel(rows[0].disease_group, bilingualMap).vi : 'Chưa có dữ liệu'}
        />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 font-semibold text-slate-800">Top nhóm bệnh theo khoảng tháng tuổi</h3>
        {chartRows.length === 0 ? (
          <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu trong khoảng tuổi này." />
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartRows} layout="vertical" margin={{ left: 24, right: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis type="category" dataKey="label" width={180} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value: number) => [`${value.toLocaleString()} ca`, 'Số ca']} />
              <Bar dataKey="case_count" radius={[0, 7, 7, 0]}>
                {chartRows.map((entry) => (
                  <Cell key={entry.disease_group} fill={entry.color} />
                ))}
                <LabelList dataKey="case_count" position="right" className="fill-slate-600 text-xs" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-4">
          <h3 className="font-semibold text-slate-800">Chi tiết bệnh theo độ tuổi</h3>
          <p className="mt-1 text-xs text-slate-500">
            {ageRangeLabel} · {periodLabel}
          </p>
        </div>

        {rows.length === 0 ? (
          <EmptyBox loading={loading || initLoading} label="Chưa có dữ liệu trong khoảng tuổi này." />
        ) : (
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="sticky top-0 z-10 bg-white">
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase text-slate-500">
                  <th className="py-3 pr-4">Nhóm bệnh</th>
                  <th className="py-3 px-3 text-right">Tổng ca</th>
                  <th className="py-3 px-3 text-right">Tháng cao nhất</th>
                  <th className="py-3 pl-3">Thời điểm ghi nhận</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.disease_group} className="border-b border-slate-100 align-top last:border-0">
                    <td className="py-3 pr-4">
                      <DiseaseLabelCell raw={row.disease_group} map={bilingualMap} />
                    </td>
                    <td className="py-3 px-3 text-right font-semibold text-slate-800">{row.case_count.toLocaleString()}</td>
                    <td className="py-3 px-3 text-right text-slate-700">
                      {row.peak_period ? `${row.peak_period} (${(row.peak_period_cases ?? 0).toLocaleString()} ca)` : '—'}
                    </td>
                    <td className="py-3 pl-3 text-slate-600">
                      {row.period_distribution && row.period_distribution.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {row.period_distribution.slice(-10).map((p) => (
                            <span key={`${row.disease_group}-${p.period}`} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                              {p.period}: {p.case_count.toLocaleString()}
                            </span>
                          ))}
                          {row.period_distribution.length > 10 && (
                            <span className="rounded-full bg-slate-50 px-2 py-0.5 text-xs text-slate-400">
                              +{row.period_distribution.length - 10} tháng
                            </span>
                          )}
                        </div>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
        <Icon size={18} className="shrink-0 text-blue-600" />
      </div>
      <p className="break-words text-2xl font-bold text-slate-800">{value}</p>
      <p className="mt-1 break-words text-xs text-slate-400">{sub}</p>
    </div>
  );
}
