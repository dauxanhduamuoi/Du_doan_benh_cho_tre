import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Loader2,
  MapPin,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
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
import { loadProvinceRegions, type ProvinceRegionRecord } from '@/lib/provinceRegions';
import { useAuth } from '../contexts/AuthContext';
import { useMinimalTheme } from '@/lib/useMinimalTheme';

const PROVINCE_COLORS = [
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
  '#65a30d',
  '#d97706',
  '#0284c7',
  '#7f1d1d',
  '#166534',
  '#581c87',
];

type RegionFilter = 'all' | ProvinceRegionRecord['mien_code'];

const REGION_OPTIONS: Array<{ value: RegionFilter; label: string; description: string }> = [
  { value: 'all', label: 'Tất cả miền', description: 'Không giới hạn khu vực' },
  { value: 'north', label: 'Miền Bắc', description: 'Bắc Bộ và vùng lân cận' },
  { value: 'central', label: 'Miền Trung', description: 'Bắc Trung Bộ, duyên hải và Tây Nguyên' },
  { value: 'south', label: 'Miền Nam', description: 'Đông Nam Bộ và Tây Nam Bộ' },
];

const RISK_BADGE: Record<string, string> = {
  Cao: 'bg-red-100 text-red-700 border-red-200',
  'Trung bình': 'bg-amber-100 text-amber-700 border-amber-200',
  Thấp: 'bg-emerald-100 text-emerald-700 border-emerald-200',
};

function normalizeText(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'd')
    .toLowerCase()
    .trim();
}

function normalizeProvinceName(value: string): string {
  return normalizeText(value)
    .replace(/\b(thanh pho|tp|tinh|t)\b/g, ' ')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function buildProvinceRegionLookup(rows: ProvinceRegionRecord[]): Map<string, Exclude<RegionFilter, 'all'>> {
  const lookup = new Map<string, Exclude<RegionFilter, 'all'>>();
  rows.forEach((row) => {
    const names = [row.province_name, ...(row.aliases ?? [])];
    names.forEach((name) => {
      const normalized = normalizeProvinceName(name);
      if (normalized) lookup.set(normalized, row.mien_code);
    });
  });
  return lookup;
}

function getProvinceRegion(
  provinceName: string,
  lookup: Map<string, Exclude<RegionFilter, 'all'>>,
): Exclude<RegionFilter, 'all'> | null {
  const normalized = normalizeProvinceName(provinceName);
  return lookup.get(normalized) ?? null;
}

function isProvinceInRegion(
  province: api.AreaOption,
  region: RegionFilter,
  lookup: Map<string, Exclude<RegionFilter, 'all'>>,
): boolean {
  if (region === 'all') return true;
  return getProvinceRegion(province.name, lookup) === region;
}

function provinceColor(code: string | null | undefined, index: number): string {
  if (!code) return PROVINCE_COLORS[index % PROVINCE_COLORS.length];
  let hash = 0;
  for (let i = 0; i < code.length; i += 1) {
    hash = (hash * 31 + code.charCodeAt(i)) % 997;
  }
  return PROVINCE_COLORS[Math.abs(hash + index) % PROVINCE_COLORS.length];
}

function riskLabel(level: string): string {
  if (level === 'Trung bình') return 'Trung bình';
  if (level === 'Thấp') return 'Thấp';
  return level;
}

function riskScore(level: string | null | undefined): number {
  const normalized = normalizeText(level ?? '');
  if (normalized.includes('cao')) return 3;
  if (normalized.includes('trung')) return 2;
  if (normalized.includes('thap')) return 1;
  return 0;
}

function scoreToRisk(score: number): string | null {
  if (score >= 3) return 'Cao';
  if (score >= 2) return 'Trung bình';
  if (score >= 1) return 'Thấp';
  return null;
}

function classifyRiskFromCases(caseCount: number, forecastRisk?: string | null): string {
  const forecastScore = riskScore(forecastRisk);
  if (forecastScore >= 3) return 'Cao';
  if (forecastScore >= 2) return 'Trung bình';
  if (caseCount >= 20) return 'Cao';
  if (caseCount >= 5) return 'Trung bình';
  return 'Thấp';
}

function aggregateDiseaseRows(rows: api.AreaDiseaseSummary[]): api.AreaDiseaseSummary[] {
  const map = new Map<string, number>();
  rows.forEach((row) => {
    map.set(row.disease_group, (map.get(row.disease_group) ?? 0) + row.case_count);
  });
  return Array.from(map.entries())
    .map(([disease_group, case_count]) => ({ disease_group, case_count }))
    .sort((a, b) => b.case_count - a.case_count);
}

function buildTargetCaseRows(
  targetProvinces: api.AreaOption[],
  allCases: api.AreaCaseSummary[],
): api.AreaCaseSummary[] {
  const caseByCode = new Map<string, api.AreaCaseSummary>();
  const caseByName = new Map<string, api.AreaCaseSummary>();

  allCases.forEach((row) => {
    if (row.area_code) caseByCode.set(row.area_code, row);
    caseByName.set(normalizeProvinceName(row.area_name), row);
  });

  return targetProvinces
    .map((province) => {
      const matched = caseByCode.get(province.code) ?? caseByName.get(normalizeProvinceName(province.name));
      return (
        matched ?? {
          area_code: province.code,
          area_name: province.name,
          level: 'province',
          case_count: 0,
          disease_groups: 0,
        }
      );
    })
    .sort((a, b) => b.case_count - a.case_count || a.area_name.localeCompare(b.area_name, 'vi'));
}

function aggregateRiskRows(rows: api.AreaLocalRisk[]): api.AreaLocalRisk[] {
  const map = new Map<
    string,
    {
      disease_group: string;
      recent_cases: number;
      riskScore: number;
      forecastScore: number;
      period_from?: string | null;
      period_to?: string | null;
    }
  >();

  rows.forEach((row) => {
    const current = map.get(row.disease_group) ?? {
      disease_group: row.disease_group,
      recent_cases: 0,
      riskScore: 0,
      forecastScore: 0,
      period_from: row.period_from,
      period_to: row.period_to,
    };
    current.recent_cases += row.recent_cases;
    current.riskScore = Math.max(current.riskScore, riskScore(row.risk_level));
    current.forecastScore = Math.max(current.forecastScore, riskScore(row.forecast_risk_level));
    if (row.period_from && (!current.period_from || row.period_from < current.period_from)) {
      current.period_from = row.period_from;
    }
    if (row.period_to && (!current.period_to || row.period_to > current.period_to)) {
      current.period_to = row.period_to;
    }
    map.set(row.disease_group, current);
  });

  return Array.from(map.values())
    .map((row) => {
      const forecast_risk_level = scoreToRisk(row.forecastScore);
      return {
        disease_group: row.disease_group,
        recent_cases: row.recent_cases,
        risk_level: classifyRiskFromCases(row.recent_cases, forecast_risk_level ?? scoreToRisk(row.riskScore)),
        forecast_risk_level,
        period_from: row.period_from,
        period_to: row.period_to,
      };
    })
    .sort((a, b) => b.recent_cases - a.recent_cases);
}

function buildRegionRecommendations(regionLabel: string, risks: api.AreaLocalRisk[]): string[] {
  const topRisks = risks.slice(0, 5);
  if (topRisks.length === 0) return [];
  return topRisks.map((risk) => {
    const level = riskLabel(risk.risk_level);
    return `${risk.disease_group}: đang ở mức ${level} tại ${regionLabel}. Phụ huynh nên theo dõi triệu chứng, giữ vệ sinh tay/hô hấp và đưa trẻ đi khám khi có dấu hiệu nặng.`;
  });
}

export default function AreaInsights() {
  const isMinimalTheme = useMinimalTheme();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [provinces, setProvinces] = useState<api.AreaOption[]>([]);
  const [provinceRegions, setProvinceRegions] = useState<ProvinceRegionRecord[]>([]);
  const [regionFilter, setRegionFilter] = useState<RegionFilter>('all');
  const [provinceCodes, setProvinceCodes] = useState<string[]>([]);
  const [provinceSearch, setProvinceSearch] = useState('');
  const [provincePickerOpen, setProvincePickerOpen] = useState(false);
  const [caseSummary, setCaseSummary] = useState<api.AreaCaseSummary[]>([]);
  const [diseaseSummary, setDiseaseSummary] = useState<api.AreaDiseaseSummary[]>([]);
  const [localRisks, setLocalRisks] = useState<api.AreaLocalRisk[]>([]);
  const [diseasePage, setDiseasePage] = useState(1);
  const [diseasePageSize, setDiseasePageSize] = useState(10);
  const [riskPage, setRiskPage] = useState(1);
  const [riskPageSize, setRiskPageSize] = useState(10);
  const [recommendations, setRecommendations] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const selectedProvinces = useMemo(
    () => provinces.filter((p) => provinceCodes.includes(p.code)),
    [provinces, provinceCodes],
  );

  const selectedRegion = useMemo(
    () => REGION_OPTIONS.find((option) => option.value === regionFilter) ?? REGION_OPTIONS[0],
    [regionFilter],
  );
  const provinceRegionLookup = useMemo(() => buildProvinceRegionLookup(provinceRegions), [provinceRegions]);
  const hasProvinceRegions = provinceRegions.length > 0;

  const activeAreaLabel = selectedProvinces.length > 0
    ? selectedProvinces.map((province) => province.name).join(', ')
    : regionFilter === 'all'
      ? 'toàn bộ dữ liệu'
      : selectedRegion.label;

  const filteredProvinces = useMemo(() => {
    const regionProvinces =
      regionFilter === 'all'
        ? provinces
        : provinces.filter((province) => isProvinceInRegion(province, regionFilter, provinceRegionLookup));
    const q = normalizeText(provinceSearch);
    if (!q) return regionProvinces;
    return regionProvinces.filter((p) => normalizeText(`${p.name} ${p.code}`).includes(q));
  }, [provinces, provinceSearch, provinceRegionLookup, regionFilter]);

  const coloredCases = useMemo(
    () =>
      (selectedProvinces.length > 0 ? caseSummary : caseSummary.slice(0, 12)).map((row, index) => ({
        ...row,
        color: provinceColor(row.area_code, index),
      })),
    [caseSummary, selectedProvinces.length],
  );
  const areaChartHeight = Math.max(360, coloredCases.length * 54);

  const totalCases = useMemo(
    () => caseSummary.reduce((sum, row) => sum + row.case_count, 0),
    [caseSummary],
  );
  const areaCountLabel =
    selectedProvinces.length > 0
      ? 'Khu vực đã chọn'
      : regionFilter !== 'all'
        ? `Khu vực trong ${selectedRegion.label}`
        : 'Khu vực có dữ liệu';

  const diseaseTotalPages = Math.max(1, Math.ceil(diseaseSummary.length / diseasePageSize));
  const diseasePageRows = useMemo(() => {
    const start = (diseasePage - 1) * diseasePageSize;
    return diseaseSummary.slice(start, start + diseasePageSize);
  }, [diseaseSummary, diseasePage, diseasePageSize]);

  const riskTotalPages = Math.max(1, Math.ceil(localRisks.length / riskPageSize));
  const riskPageRows = useMemo(() => {
    const start = (riskPage - 1) * riskPageSize;
    return localRisks.slice(start, start + riskPageSize);
  }, [localRisks, riskPage, riskPageSize]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [prov, regionRows] = await Promise.all([api.listAreaProvinces(), loadProvinceRegions()]);
      setProvinces(prov);
      setProvinceRegions(regionRows);
      const regionLookup = buildProvinceRegionLookup(regionRows);

      const selectedProvinceSet = new Set(provinceCodes);
      const targetProvinces =
        provinceCodes.length > 0
          ? prov.filter((province) => selectedProvinceSet.has(province.code))
          : regionFilter !== 'all'
            ? prov.filter((province) => isProvinceInRegion(province, regionFilter, regionLookup))
            : [];

      if (targetProvinces.length > 0) {
        const allCases = await api.getAreaCaseSummary({ limit: 200 });
        const targetCases = buildTargetCaseRows(targetProvinces, allCases);
        const targetDataCodes = Array.from(
          new Set(
            targetCases
              .filter((row) => row.case_count > 0 && row.area_code)
              .map((row) => row.area_code as string),
          ),
        );
        const [diseaseLists, riskLists] = await Promise.all([
          Promise.all(
            targetDataCodes.map((provinceCode) =>
              api.getAreaDiseaseSummary({ provinceCode, limit: 200 }).catch(() => []),
            ),
          ),
          Promise.all(
            targetDataCodes.map((provinceCode) =>
              api.getAreaLocalRisks({ provinceCode, limit: 200 }).catch(() => []),
            ),
          ),
        ]);
        const diseases = aggregateDiseaseRows(diseaseLists.flat()).slice(0, 200);
        const risks = aggregateRiskRows(riskLists.flat()).slice(0, 200);
        const targetLabel =
          provinceCodes.length > 0
            ? targetProvinces.map((province) => province.name).join(', ')
            : selectedRegion.label;
        setCaseSummary(targetCases);
        setDiseaseSummary(diseases);
        setLocalRisks(risks);
        setRecommendations(buildRegionRecommendations(targetLabel, risks));
        return;
      }

      const [cases, diseases, risks, rec] = await Promise.all([
        api.getAreaCaseSummary({ limit: 200 }),
        api.getAreaDiseaseSummary({ limit: 200 }),
        api.getAreaLocalRisks({ limit: 200 }),
        api.getAreaRecommendations({}).catch(() => null),
      ]);
      setCaseSummary(cases);
      setDiseaseSummary(diseases);
      setLocalRisks(risks);
      setRecommendations(rec?.recommendations ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [provinceCodes, regionFilter, selectedRegion.label]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setDiseasePage(1);
    setRiskPage(1);
  }, [provinceCodes, regionFilter, diseasePageSize, riskPageSize]);

  useEffect(() => {
    if (diseasePage > diseaseTotalPages) setDiseasePage(diseaseTotalPages);
  }, [diseasePage, diseaseTotalPages]);

  useEffect(() => {
    if (riskPage > riskTotalPages) setRiskPage(riskTotalPages);
  }, [riskPage, riskTotalPages]);

  async function handleSyncDefaults() {
    setSyncing(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.syncDefaultAreas();
      setMessage(res.message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="space-y-6">
      <section
        className={`relative rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${
          provincePickerOpen ? 'z-50' : 'z-0'
        }`}
      >
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-lg bg-blue-50 p-2 text-blue-600 ring-1 ring-blue-100">
              <MapPin size={22} />
            </div>
            <div className="min-w-0">
              <h2 className="text-xl font-semibold text-slate-800">Thống kê theo tỉnh/thành phố</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                Dữ liệu khu vực được lấy từ phần sau dấu phẩy cuối cùng của cột{' '}
                <span className="font-mono text-slate-700">full_address</span>. Các tỉnh/thành phố được tô màu riêng
                để dễ so sánh khi số lượng khu vực tăng. Bộ lọc Bắc/Trung/Nam chỉ hoạt động sau khi import file
                phân miền tỉnh/thành trong mục Import dữ liệu.
              </p>
            </div>
          </div>

          <div className="w-full shrink-0 space-y-3 xl:w-[420px]">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="mb-3">
                <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Lọc theo miền
                </span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-2">
                  {REGION_OPTIONS.map((option) => {
                    const active = option.value === regionFilter && selectedProvinces.length === 0;
                    const disabled = option.value !== 'all' && !hasProvinceRegions;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          if (disabled) return;
                          setRegionFilter(option.value);
                          setProvinceCodes([]);
                          setProvinceSearch('');
                          setProvincePickerOpen(false);
                        }}
                        className={`rounded-lg border px-3 py-2 text-left transition ${
                          active
                            ? 'border-blue-500 bg-blue-50 text-blue-700 shadow-sm'
                            : disabled
                              ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400 opacity-70'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50/60'
                        }`}
                      >
                        <span className="block text-sm font-semibold">{option.label}</span>
                        <span className="mt-0.5 block text-[11px] leading-4 text-slate-400">{option.description}</span>
                      </button>
                    );
                  })}
                </div>
                {!hasProvinceRegions && (
                  <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-700">
                    Chưa import file phân miền tỉnh/thành. Các bộ lọc Miền Bắc, Miền Trung, Miền Nam tạm thời không hoạt động.
                  </p>
                )}
              </div>

              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Lọc tỉnh/thành phố
                </span>
                {(selectedProvinces.length > 0 || regionFilter !== 'all') && (
                  <button
                    onClick={() => {
                      setRegionFilter('all');
                      setProvinceCodes([]);
                      setProvinceSearch('');
                    }}
                    className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs text-slate-500 ring-1 ring-slate-200 hover:text-red-600"
                  >
                    <X size={12} />
                    Bỏ lọc
                  </button>
                )}
              </div>
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  value={provinceSearch}
                  onFocus={() => setProvincePickerOpen(true)}
                  onBlur={() => {
                    window.setTimeout(() => setProvincePickerOpen(false), 120);
                  }}
                  onChange={(e) => {
                    setProvinceSearch(e.target.value);
                    setProvincePickerOpen(true);
                  }}
                  placeholder="Tìm nhanh: Hồ Chí Minh, Đồng Nai..."
                  className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {provincePickerOpen && (
                  <div className="absolute left-0 right-0 top-[calc(100%+6px)] z-[100] max-h-72 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setProvinceCodes([]);
                        setProvinceSearch('');
                        setProvincePickerOpen(false);
                      }}
                      className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                        selectedProvinces.length === 0 ? 'bg-blue-50 text-blue-700' : 'text-slate-700'
                      }`}
                    >
                      <span className="font-medium">
                        {regionFilter === 'all'
                          ? 'Tất cả tỉnh/thành phố'
                          : `Tất cả tỉnh/thành phố trong ${selectedRegion.label}`}
                      </span>
                      {selectedProvinces.length === 0 && <span className="text-xs font-semibold">Đang chọn</span>}
                    </button>
                    {filteredProvinces.length > 0 ? (
                      filteredProvinces.map((p, index) => {
                        const active = provinceCodes.includes(p.code);
                        return (
                          <button
                            key={p.code}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                              setProvinceCodes((current) =>
                                current.includes(p.code)
                                  ? current.filter((code) => code !== p.code)
                                  : [...current, p.code],
                              );
                            }}
                            className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                              active ? 'bg-blue-50 text-blue-700' : 'text-slate-700'
                            }`}
                          >
                            <span
                              className="h-3 w-3 rounded-full shrink-0"
                              style={{ backgroundColor: provinceColor(p.code, index) }}
                            />
                            <span className="min-w-0 flex-1 truncate">{p.name}</span>
                            <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
                              {p.code}
                            </span>
                            {active && <span className="shrink-0 text-xs font-semibold text-blue-700">Đã chọn</span>}
                          </button>
                        );
                      })
                    ) : (
                      <div className="px-3 py-3 text-sm text-slate-500">
                        Không tìm thấy tỉnh/thành phố phù hợp.
                      </div>
                    )}
                  </div>
                )}
              </div>
              {selectedProvinces.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 rounded-lg bg-white px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-200">
                  {selectedProvinces.map((province, index) => (
                    <button
                      key={province.code}
                      type="button"
                      onClick={() => setProvinceCodes((current) => current.filter((code) => code !== province.code))}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200 hover:text-red-600"
                      title="Bỏ chọn tỉnh/thành phố này"
                    >
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: provinceColor(province.code, index) }}
                      />
                      <span className="min-w-0 truncate">{province.name}</span>
                      <X size={11} />
                    </button>
                  ))}
                </div>
              )}
              {selectedProvinces.length === 0 && regionFilter !== 'all' && (
                <div className="mt-3 flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-200">
                  <span className="h-3 w-3 rounded-full bg-blue-500" />
                  <span className="min-w-0 truncate font-medium">Đang lọc: {selectedRegion.label}</span>
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={load}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
                Làm mới
              </button>
              {isAdmin && (
                <button
                  onClick={handleSyncDefaults}
                  disabled={syncing}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                >
                  {syncing ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                  Đồng bộ mặc định
                </button>
              )}
            </div>
          </div>
        </div>
      </section>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {message && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <StatCard icon={MapPin} label={areaCountLabel} value={caseSummary.length} accent="#2563eb" />
        <StatCard
          icon={Activity}
          label={selectedProvinces.length > 0 || regionFilter !== 'all' ? `Số ca tại ${activeAreaLabel}` : 'Tổng số ca hiện tại'}
          value={totalCases}
          accent="#dc2626"
        />
        <StatCard icon={Sparkles} label="Nhóm bệnh nổi bật" value={diseaseSummary.length} accent="#16a34a" />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-blue-600" />
              <h3 className="font-semibold text-slate-800">
                {selectedProvinces.length > 0 ? 'Các khu vực đã chọn' : 'Khu vực có số ca cao'}
              </h3>
            </div>
            <span className="text-xs text-slate-400">
              {selectedProvinces.length > 0
                ? `${coloredCases.length} tỉnh/thành phố đã chọn`
                : `Top ${coloredCases.length} tỉnh/thành phố`}
            </span>
          </div>
          {caseSummary.length === 0 ? (
            <Empty loading={loading} text="Chưa có dữ liệu khu vực. Hãy import file có cột full_address." />
          ) : (
            <div className="max-h-[720px] overflow-y-auto pr-2">
              <ResponsiveContainer width="100%" height={areaChartHeight}>
                <BarChart data={coloredCases} layout="vertical" margin={{ left: 20, right: 34, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 12, fill: '#64748b' }} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="area_name"
                    width={155}
                    tick={{ fontSize: 12, fill: '#475569' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: '#f8fafc' }}
                    contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0' }}
                    formatter={(value: number) => [`${value.toLocaleString()} ca`, 'Số ca']}
                  />
                  <Bar
                    dataKey="case_count"
                    name="Số ca"
                    radius={[0, 6, 6, 0]}
                    minPointSize={3}
                    isAnimationActive={!isMinimalTheme}
                  >
                    {coloredCases.map((entry) => (
                      <Cell key={entry.area_code ?? entry.area_name} fill={entry.color} />
                    ))}
                    <LabelList
                      dataKey="case_count"
                      position="right"
                      formatter={(value: number) => value.toLocaleString()}
                      style={{ fill: '#334155', fontSize: 11, fontWeight: 700 }}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 font-semibold text-slate-800">Bảng xếp hạng khu vực</h3>
          {coloredCases.length === 0 ? (
            <Empty loading={loading} text="Chưa có dữ liệu." />
          ) : (
            <div className="max-h-[720px] space-y-2 overflow-y-auto pr-1">
              {coloredCases.map((row, index) => (
                <div
                  key={row.area_code ?? row.area_name}
                  className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
                >
                  <span className="w-6 text-right text-xs font-bold text-slate-400">{index + 1}</span>
                  <span className="h-3 w-3 rounded-full shrink-0" style={{ backgroundColor: row.color }} />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">{row.area_name}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs font-bold text-slate-700 ring-1 ring-slate-200">
                    {row.case_count.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="font-semibold text-slate-800">
              Nhóm bệnh xuất hiện nhiều {selectedProvinces.length > 0 || regionFilter !== 'all' ? `tại ${activeAreaLabel}` : 'theo toàn bộ dữ liệu'}
            </h3>
            <PageSizeSelect value={diseasePageSize} onChange={setDiseasePageSize} />
          </div>
          {diseaseSummary.length === 0 ? (
            <Empty loading={loading} text="Chưa có dữ liệu nhóm bệnh cho khu vực này." />
          ) : (
            <>
              <div className="space-y-2">
                {diseasePageRows.map((row, idx) => (
                  <div
                    key={`${row.disease_group}-${idx}`}
                    className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
                  >
                    <p className="min-w-0 break-words text-sm font-medium text-slate-800">{row.disease_group}</p>
                    <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-sm font-semibold text-slate-700 ring-1 ring-slate-200">
                      {row.case_count.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
              <PaginationControls
                page={diseasePage}
                totalPages={diseaseTotalPages}
                totalRows={diseaseSummary.length}
                pageSize={diseasePageSize}
                onPageChange={setDiseasePage}
              />
            </>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="font-semibold text-slate-800">Nguy cơ bệnh cho phụ huynh theo nơi sinh sống</h3>
              <p className="mt-1 text-sm text-slate-500">Mức độ nguy cơ dựa trên dự báo từ AI.</p>
            </div>
            <PageSizeSelect value={riskPageSize} onChange={setRiskPageSize} />
          </div>
          {localRisks.length === 0 ? (
            <Empty loading={loading} text="Chưa có dữ liệu nguy cơ tại khu vực này." />
          ) : (
            <>
              <div className="space-y-3">
                {riskPageRows.map((row, idx) => (
                  <div key={`${row.disease_group}-${idx}`} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="break-words font-semibold text-slate-800">{row.disease_group}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          Số ca ghi nhận: {row.recent_cases.toLocaleString()}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${
                          RISK_BADGE[row.risk_level] ?? 'bg-slate-100 text-slate-700 border-slate-200'
                        }`}
                      >
                        {riskLabel(row.risk_level)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              <PaginationControls
                page={riskPage}
                totalPages={riskTotalPages}
                totalRows={localRisks.length}
                pageSize={riskPageSize}
                onPageChange={setRiskPage}
              />
            </>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 font-semibold text-slate-800">Khuyến nghị phòng bệnh theo khu vực</h3>
        {recommendations.length === 0 ? (
          <Empty loading={loading} text="Chưa có khuyến nghị." />
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {recommendations.map((item, idx) => (
              <div key={idx} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
                {item}
              </div>
            ))}
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
  accent,
}: {
  icon: typeof MapPin;
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" style={{ borderLeft: `4px solid ${accent}` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-slate-500">{label}</p>
          <p className="mt-1 text-3xl font-bold text-slate-800">{value.toLocaleString()}</p>
        </div>
        <div className="rounded-lg p-2" style={{ backgroundColor: `${accent}18`, color: accent }}>
          <Icon size={20} />
        </div>
      </div>
    </div>
  );
}

function PageSizeSelect({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-xs text-slate-500">
      Hiển thị
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {[5, 10, 20, 50].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      dòng
    </label>
  );
}

function PaginationControls({
  page,
  totalPages,
  totalRows,
  pageSize,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  totalRows: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const from = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, totalRows);

  return (
    <div className="mt-4 flex flex-col gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
      <span>
        Hiển thị {from}-{to} / {totalRows}
      </span>
      {totalPages > 1 && (
        <div className="flex items-center gap-1">
          <button
            onClick={() => onPageChange(1)}
            disabled={page === 1}
            className="rounded border border-slate-200 bg-white px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
          >
            «
          </button>
          <button
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page === 1}
            className="rounded border border-slate-200 bg-white px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
          >
            ‹
          </button>
          <span className="px-2 font-medium text-slate-700">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="rounded border border-slate-200 bg-white px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
          >
            ›
          </button>
          <button
            onClick={() => onPageChange(totalPages)}
            disabled={page === totalPages}
            className="rounded border border-slate-200 bg-white px-2 py-1 hover:bg-slate-50 disabled:opacity-40"
          >
            »
          </button>
        </div>
      )}
    </div>
  );
}

function Empty({ loading, text }: { loading: boolean; text: string }) {
  return (
    <div className="flex h-[180px] items-center justify-center text-sm text-slate-400">
      {loading ? (
        <span className="inline-flex items-center gap-2">
          <Loader2 size={16} className="animate-spin" /> Đang tải
        </span>
      ) : (
        text
      )}
    </div>
  );
}
