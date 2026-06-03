import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FileText,
  FileSpreadsheet,
  FileBarChart,
  Download,
  Calendar,
  Filter,
  Clock,
  CheckCircle2,
  Settings as SettingsIcon,
  Sparkles,
  Printer,
  Share2,
  Search,
  ChevronDown,
  X,
  Plus,
  Layers,
  FileType2,
  RefreshCcw,
  AlertTriangle,
} from 'lucide-react';
import * as api from '@/lib/api';
import {
  downloadReport,
  formatBytes,
  type ReportBundle,
  type ReportColumn,
  type ReportFormat,
} from '@/lib/reports';
import { useT } from '@/lib/i18n';
import { useAuth } from '../contexts/AuthContext';

type ReportType = 'overview' | 'seasonal' | 'disease' | 'forecast' | 'age_months' | 'month_year' | 'custom';
type DateRange = '7d' | '30d' | '90d' | 'quarter' | 'year' | 'custom';

interface ReportTemplate {
  id: string;
  name: string;
  description: string;
  type: ReportType;
  icon: typeof FileText;
  color: string;
  bgColor: string;
  popular?: boolean;
}

interface ReportHistoryItem {
  id: string;
  name: string;
  type: ReportType;
  format: ReportFormat;
  createdAt: string;
  size: string;
  status: 'ready' | 'processing' | 'failed';
  createdBy: string;
  error?: string;
}

const HISTORY_KEY = 'sd_report_history';

function loadHistory(): ReportHistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ReportHistoryItem[];
  } catch {
    return [];
  }
}

function saveHistory(items: ReportHistoryItem[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 50)));
  } catch {
    // ignore quota
  }
}

type TropicalSeason = 'dry' | 'rainy';

const TROPICAL_SEASONS: TropicalSeason[] = ['dry', 'rainy'];

// Miền Nam/TP.HCM dùng 2 mùa: mùa khô và mùa mưa.
// Mùa khô: tháng 12, 1, 2, 3, 4. Mùa mưa: tháng 5-11.
const SEASON_BY_MONTH: Record<number, TropicalSeason> = {
  1: 'dry', 2: 'dry', 3: 'dry', 4: 'dry',
  5: 'rainy', 6: 'rainy', 7: 'rainy', 8: 'rainy', 9: 'rainy', 10: 'rainy', 11: 'rainy',
  12: 'dry',
};

export default function Reports() {
  const t = useT();
  const { user } = useAuth();

  const reportTypeLabels: Record<ReportType, string> = useMemo(
    () => ({
      overview: t('reports.types.overview'),
      seasonal: t('reports.types.seasonal'),
      disease: t('reports.types.disease'),
      forecast: t('reports.types.forecast'),
      age_months: t('reports.types.ageMonths'),
      month_year: t('reports.types.monthYear'),
      custom: t('reports.types.custom'),
    }),
    [t],
  );

  const reportTypes: { id: ReportType; label: string; description: string }[] = useMemo(
    () => [
      { id: 'overview', label: t('reports.types.overview'), description: t('reports.types.overview.desc') },
      { id: 'seasonal', label: t('reports.types.seasonal'), description: t('reports.types.seasonal.desc') },
      { id: 'disease', label: t('reports.types.disease'), description: t('reports.types.disease.desc') },
      { id: 'forecast', label: t('reports.types.forecast'), description: t('reports.types.forecast.desc') },
      { id: 'age_months', label: t('reports.types.ageMonths'), description: t('reports.types.ageMonths.desc') },
      { id: 'month_year', label: t('reports.types.monthYear'), description: t('reports.types.monthYear.desc') },
      { id: 'custom', label: t('reports.types.custom'), description: t('reports.types.custom.desc') },
    ],
    [t],
  );

  const formatOptions: { id: ReportFormat; label: string; icon: typeof FileText; color: string }[] = useMemo(
    () => [
      { id: 'pdf', label: t('reports.format.pdf'), icon: FileText, color: 'text-red-600 bg-red-50 border-red-200' },
      { id: 'excel', label: t('reports.format.excel'), icon: FileSpreadsheet, color: 'text-emerald-600 bg-emerald-50 border-emerald-200' },
      { id: 'csv', label: t('reports.format.csv'), icon: FileType2, color: 'text-blue-600 bg-blue-50 border-blue-200' },
      { id: 'word', label: t('reports.format.word'), icon: FileBarChart, color: 'text-indigo-600 bg-indigo-50 border-indigo-200' },
    ],
    [t],
  );

  const dateRangeOptions: { id: DateRange; label: string }[] = useMemo(
    () => [
      { id: '7d', label: t('reports.dateRange.7d') },
      { id: '30d', label: t('reports.dateRange.30d') },
      { id: '90d', label: t('reports.dateRange.90d') },
      { id: 'quarter', label: t('reports.dateRange.quarter') },
      { id: 'year', label: t('reports.dateRange.year') },
      { id: 'custom', label: t('reports.dateRange.custom') },
    ],
    [t],
  );

  const templates: ReportTemplate[] = useMemo(
    () => [
      {
        id: 't1',
        name: t('reports.types.overview'),
        description: t('reports.types.overview.desc'),
        type: 'overview',
        icon: FileBarChart,
        color: 'text-blue-600',
        bgColor: 'bg-blue-50',
        popular: true,
      },
      {
        id: 't2',
        name: t('reports.types.seasonal'),
        description: t('reports.types.seasonal.desc'),
        type: 'seasonal',
        icon: Layers,
        color: 'text-emerald-600',
        bgColor: 'bg-emerald-50',
        popular: true,
      },
      {
        id: 't3',
        name: t('reports.types.disease'),
        description: t('reports.types.disease.desc'),
        type: 'disease',
        icon: FileText,
        color: 'text-red-600',
        bgColor: 'bg-red-50',
      },
      {
        id: 't4',
        name: t('reports.types.forecast'),
        description: t('reports.types.forecast.desc'),
        type: 'forecast',
        icon: Sparkles,
        color: 'text-indigo-600',
        bgColor: 'bg-indigo-50',
      },
      {
        id: 't5',
        name: t('reports.types.overview'),
        description: t('reports.dateRange.30d'),
        type: 'overview',
        icon: Calendar,
        color: 'text-amber-600',
        bgColor: 'bg-amber-50',
      },
      {
        id: 't6',
        name: t('reports.types.custom'),
        description: t('reports.types.custom.desc'),
        type: 'custom',
        icon: Sparkles,
        color: 'text-purple-600',
        bgColor: 'bg-purple-50',
      },
    ],
    [t],
  );

  const statusStyles: Record<ReportHistoryItem['status'], string> = {
    ready: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    processing: 'bg-amber-50 text-amber-700 border-amber-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
  };

  const statusLabels: Record<ReportHistoryItem['status'], string> = {
    ready: t('common.ready'),
    processing: t('common.processing'),
    failed: t('common.failed'),
  };

  // ===== Configuration =====
  const [reportType, setReportType] = useState<ReportType>('overview');
  const [reportFormat, setReportFormat] = useState<ReportFormat>('csv');
  const [dataType, setDataType] = useState<'train_history' | 'predict_current'>('predict_current');
  const [dateRange, setDateRange] = useState<DateRange>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');

  const [allDiseases, setAllDiseases] = useState<string[]>([]);
  const [selectedDiseases, setSelectedDiseases] = useState<string[]>([]);

  const [includeTable, setIncludeTable] = useState(true);
  const [includeSummary, setIncludeSummary] = useState(true);
  const [includeRecommendation, setIncludeRecommendation] = useState(false);

  const [history, setHistory] = useState<ReportHistoryItem[]>(() => loadHistory());
  const [historyFilter, setHistoryFilter] = useState<'all' | ReportType>('all');
  const [historySearch, setHistorySearch] = useState('');

  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    saveHistory(history);
  }, [history]);

  const loadDiseases = useCallback(async () => {
    try {
      const groups = await api.getTopDiseaseGroups(dataType, 100);
      setAllDiseases(groups.map((g) => g.disease_group));
    } catch {
      setAllDiseases([]);
    }
  }, [dataType]);

  useEffect(() => {
    loadDiseases();
  }, [loadDiseases]);

  const handleApplyTemplate = (tpl: ReportTemplate) => {
    setReportType(tpl.type);
    if (tpl.id === 't1') setDateRange('7d');
    if (tpl.id === 't5') setDateRange('30d');
  };

  const labelOfDateRange = (): string => {
    if (dateRange === 'custom' && customFrom && customTo) return `${customFrom} → ${customTo}`;
    return dateRangeOptions.find((d) => d.id === dateRange)?.label ?? '';
  };

  const labelOfResolvedRange = (rows: api.MonthlyStat[]): string => {
    const bounds = getDateRangeBounds(rows, dateRange, customFrom, customTo);
    const base = labelOfDateRange();
    if (!bounds.from && !bounds.to) return base;
    if (bounds.from && bounds.to) return `${base} (${bounds.from} → ${bounds.to})`;
    if (bounds.from) return `${base} (từ ${bounds.from})`;
    return `${base} (đến ${bounds.to})`;
  };

  // ===== Report builders =====

  const buildOverview = async (): Promise<ReportBundle> => {
    const rows = await api.getMonthlyStatistics(dataType);
    const filtered = filterByDateRange(rows, dateRange, customFrom, customTo);
    const top = aggregateByDisease(filtered).slice(0, 10);

    const columns: ReportColumn[] = [
      { key: 'disease_group', label: t('col.diseaseGroup') },
      { key: 'case_count', label: t('col.cases'), align: 'right', format: (v) => String(v ?? 0) },
    ];

    const totalCases = filtered.reduce((sum, row) => sum + row.case_count, 0);
    const totalPeriods = new Set(filtered.map((row) => row.period)).size;
    const totalGroups = new Set(filtered.map((row) => row.disease_group)).size;

    return {
      title: `${t('reports.types.overview')} (${dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')})`,
      subtitle: `${t('reports.settings.dateRange')}: ${labelOfResolvedRange(rows)}`,
      generatedAt: new Date().toISOString(),
      columns,
      rows: top as unknown as Record<string, unknown>[],
      summary: [
        { label: t('dashboard.totalCases'), value: totalCases.toLocaleString() },
        { label: t('dashboard.totalPeriods'), value: totalPeriods },
        { label: t('dashboard.totalGroups'), value: totalGroups },
      ],
    };
  };

  const buildSeasonal = async (): Promise<ReportBundle> => {
    const rows = await api.getMonthlyStatistics(dataType);
    const filtered = filterByDateRange(rows, dateRange, customFrom, customTo);

    const bySeason = new Map<string, number>();
    for (const r of filtered) {
      const m = parseInt(r.period.slice(5, 7), 10);
      const s = SEASON_BY_MONTH[m] ?? 'dry';
      bySeason.set(s, (bySeason.get(s) ?? 0) + r.case_count);
    }

    const seasonalRows = TROPICAL_SEASONS.map((s) => ({
      season: t(`season.${s}`),
      case_count: bySeason.get(s) ?? 0,
    }));

    const columns: ReportColumn[] = [
      { key: 'season', label: t('seasonal.peakSeason') },
      { key: 'case_count', label: t('col.cases'), align: 'right', format: (v) => String(v ?? 0) },
    ];

    const total = seasonalRows.reduce((a, b) => a + b.case_count, 0);
    const peak = seasonalRows.slice().sort((a, b) => b.case_count - a.case_count)[0];

    return {
      title: t('reports.types.seasonal'),
      subtitle: `${dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')} · ${labelOfResolvedRange(rows)}`,
      generatedAt: new Date().toISOString(),
      columns,
      rows: seasonalRows as unknown as Record<string, unknown>[],
      summary: [
        { label: t('common.total'), value: total.toLocaleString() },
        { label: t('seasonal.peak'), value: `${peak.season} (${peak.case_count})` },
      ],
    };
  };

  const buildDisease = async (): Promise<ReportBundle> => {
    const rows = await api.getMonthlyStatistics(dataType);
    const filtered = filterByDateRange(rows, dateRange, customFrom, customTo);
    const diseaseSet = new Set(selectedDiseases);

    const scope = diseaseSet.size > 0 ? filtered.filter((r) => diseaseSet.has(r.disease_group)) : filtered;

    const columns: ReportColumn[] = [
      { key: 'period', label: t('col.period') },
      { key: 'disease_group', label: t('col.diseaseGroup') },
      { key: 'case_count', label: t('col.cases'), align: 'right', format: (v) => String(v ?? 0) },
    ];

    const byKey = new Map<string, { period: string; disease_group: string; case_count: number }>();
    for (const r of scope) {
      const k = `${r.period}|${r.disease_group}`;
      const cur = byKey.get(k);
      if (cur) cur.case_count += r.case_count;
      else byKey.set(k, { period: r.period, disease_group: r.disease_group, case_count: r.case_count });
    }

    const merged = Array.from(byKey.values()).sort((a, b) => {
      if (a.period !== b.period) return a.period.localeCompare(b.period);
      return b.case_count - a.case_count;
    });

    return {
      title: `${t('reports.types.disease')} (${dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')})`,
      subtitle: labelOfResolvedRange(rows),
      generatedAt: new Date().toISOString(),
      columns,
      rows: merged as unknown as Record<string, unknown>[],
      summary: [
        { label: t('common.rows'), value: merged.length },
        { label: t('common.total'), value: merged.reduce((a, b) => a + b.case_count, 0).toLocaleString() },
      ],
    };
  };

  const buildForecast = async (): Promise<ReportBundle> => {
    const allRows = await api.getForecastGroupSummary();
    const rows = selectedDiseases.length > 0
      ? allRows.filter((row) => selectedDiseases.includes(row.disease_group))
      : allRows;

    const columns: ReportColumn[] = [
      { key: 'forecast_period', label: t('col.period') },
      { key: 'disease_group', label: t('col.diseaseGroup') },
      { key: 'previous_cases', label: t('col.previous'), align: 'right', format: (v) => String(v ?? 0) },
      { key: 'predicted_cases', label: t('col.predicted'), align: 'right', format: (v) => String(v ?? 0) },
      {
        key: 'change_percent',
        label: t('col.changePercent'),
        align: 'right',
        format: (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`),
      },
      { key: 'trend', label: t('col.trend') },
      { key: 'risk_level', label: t('col.risk') },
    ];

    const high = rows.filter((r) => r.risk_level === 'Cao').length;

    return {
      title: t('reports.types.forecast'),
      subtitle: `API: /api/forecast/group-summary`,
      generatedAt: new Date().toISOString(),
      columns,
      rows: rows as unknown as Record<string, unknown>[],
      summary: [
        { label: t('common.rows'), value: rows.length },
        { label: t('forecast.highRisk'), value: high },
      ],
    };
  };

  const buildAgeMonths = async (): Promise<ReportBundle> => {
    const monthlyRows = await api.getMonthlyStatistics(dataType);
    const bounds = getDateRangeBounds(monthlyRows, dateRange, customFrom, customTo);
    const periodFrom = bounds.from;
    const periodTo = bounds.to;
    const data = await api.getReportByAgeMonths({ dataType, periodFrom, periodTo });

    // Flatten thành rows: 1 dòng = 1 (bucket × disease_group)
    const flat = data.buckets.flatMap((b) =>
      b.rows.map((r) => ({
        age_bucket: b.age_bucket,
        disease_group: r.disease_group,
        case_count: r.case_count,
      })),
    );

    const columns: ReportColumn[] = [
      { key: 'age_bucket', label: t('reports.col.ageBucket') },
      { key: 'disease_group', label: t('col.diseaseGroup') },
      { key: 'case_count', label: t('col.cases'), align: 'right', format: (v) => String(v ?? 0) },
    ];

    return {
      title: t('reports.types.ageMonths'),
      subtitle: `${dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')} · ${labelOfResolvedRange(monthlyRows)}`,
      generatedAt: new Date().toISOString(),
      columns,
      rows: flat as unknown as Record<string, unknown>[],
      summary: data.buckets.map((b) => ({ label: b.age_bucket, value: b.total })),
    };
  };

  const buildMonthYear = async (): Promise<ReportBundle> => {
    const [data, monthlyRows] = await Promise.all([
      api.getReportByMonthYear(dataType),
      api.getMonthlyStatistics(dataType),
    ]);
    const bounds = getDateRangeBounds(monthlyRows, dateRange, customFrom, customTo);

    // Flatten dạng (year, month, case_count)
    const flat = data.rows.flatMap((y) =>
      y.months.map((m) => ({
        year: y.year,
        month: `T${m.month}`,
        period: `${y.year}-${String(m.month).padStart(2, '0')}`,
        case_count: m.case_count,
      })),
    ).filter((row) => isPeriodInBounds(row.period, bounds));

    const columns: ReportColumn[] = [
      { key: 'year', label: t('reports.col.year') },
      { key: 'month', label: t('reports.col.month') },
      { key: 'case_count', label: t('col.cases'), align: 'right', format: (v) => String(v ?? 0) },
    ];

    return {
      title: t('reports.types.monthYear'),
      subtitle: `${dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')} · ${labelOfResolvedRange(monthlyRows)}`,
      generatedAt: new Date().toISOString(),
      columns,
      rows: flat as unknown as Record<string, unknown>[],
      summary: Array.from(
        flat.reduce((map, row) => {
          map.set(String(row.year), (map.get(String(row.year)) ?? 0) + row.case_count);
          return map;
        }, new Map<string, number>()),
      ).map(([label, value]) => ({ label, value })),
    };
  };

  const buildCustom = async (): Promise<ReportBundle> => {
    const rows = await api.getMonthlyStatistics(dataType);
    const filtered = filterByDateRange(rows, dateRange, customFrom, customTo);
    const groups = aggregateByDisease(filtered);
    const scope = selectedDiseases.length > 0
      ? groups.filter((g) => selectedDiseases.includes(g.disease_group))
      : groups.slice(0, 20);

    const columns: ReportColumn[] = [
      { key: 'disease_group', label: t('col.diseaseGroup') },
      { key: 'case_count', label: t('col.cases'), align: 'right' },
    ];

    return {
      title: t('reports.types.custom'),
      subtitle: labelOfResolvedRange(rows),
      generatedAt: new Date().toISOString(),
      columns,
      rows: scope as unknown as Record<string, unknown>[],
      summary: [
        { label: t('common.rows'), value: scope.length },
        {
          label: t('common.total'),
          value: scope.reduce((a, b) => a + b.case_count, 0).toLocaleString(),
        },
      ],
    };
  };

  const handleGenerate = async () => {
    setError(null);
    setIsGenerating(true);

    const newId = `r${Date.now()}`;
    const pending: ReportHistoryItem = {
      id: newId,
      name: `${reportTypeLabels[reportType]} - ${new Date().toLocaleString()}`,
      type: reportType,
      format: reportFormat,
      createdAt: new Date().toLocaleString(),
      size: '—',
      status: 'processing',
      createdBy: user?.full_name || user?.username || 'system',
    };
    setHistory((h) => [pending, ...h]);

    try {
      let bundle: ReportBundle;
      switch (reportType) {
        case 'overview': bundle = await buildOverview(); break;
        case 'seasonal': bundle = await buildSeasonal(); break;
        case 'disease': bundle = await buildDisease(); break;
        case 'forecast': bundle = await buildForecast(); break;
        case 'age_months': bundle = await buildAgeMonths(); break;
        case 'month_year': bundle = await buildMonthYear(); break;
        case 'custom':
        default: bundle = await buildCustom();
      }

      const recommendations = includeRecommendation ? buildRecommendations(reportType, bundle) : undefined;
      if (!includeTable) bundle = { ...bundle, rows: [] };
      if (!includeSummary) bundle = { ...bundle, summary: undefined };
      if (recommendations) bundle = { ...bundle, recommendations };

      const result = downloadReport(bundle, reportFormat);

      setHistory((h) =>
        h.map((r) =>
          r.id === newId
            ? {
                ...r,
                status: 'ready',
                name: result.filename,
                size: formatBytes(result.sizeBytes),
              }
            : r,
        ),
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setHistory((h) =>
        h.map((r) =>
          r.id === newId ? { ...r, status: 'failed', error: msg, size: '—' } : r,
        ),
      );
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDelete = (id: string) => {
    setHistory((h) => h.filter((r) => r.id !== id));
  };

  const filteredHistory = useMemo(() => {
    return history.filter((r) => {
      if (historyFilter !== 'all' && r.type !== historyFilter) return false;
      if (historySearch && !r.name.toLowerCase().includes(historySearch.toLowerCase())) return false;
      return true;
    });
  }, [history, historyFilter, historySearch]);

  const selectedFormat = formatOptions.find((f) => f.id === reportFormat)!;

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm flex items-start gap-2">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <StatCard
          icon={FileText}
          label={t('reports.stats.total')}
          value={history.length.toString()}
          iconBg="bg-blue-100"
          iconColor="text-blue-600"
          borderColor="border-l-blue-500"
        />
        <StatCard
          icon={CheckCircle2}
          label={t('reports.stats.ready')}
          value={history.filter((r) => r.status === 'ready').length.toString()}
          iconBg="bg-emerald-100"
          iconColor="text-emerald-600"
          borderColor="border-l-emerald-500"
        />
        <StatCard
          icon={Clock}
          label={t('reports.stats.processing')}
          value={history.filter((r) => r.status === 'processing').length.toString()}
          iconBg="bg-amber-100"
          iconColor="text-amber-600"
          borderColor="border-l-amber-500"
        />
        <StatCard
          icon={AlertTriangle}
          label={t('reports.stats.failed')}
          value={history.filter((r) => r.status === 'failed').length.toString()}
          iconBg="bg-red-100"
          iconColor="text-red-600"
          borderColor="border-l-red-500"
        />
      </div>

      <Section title={t('reports.templates.title')} subtitle={t('reports.templates.subtitle')} icon={Sparkles}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {templates.map((tpl) => {
            const Icon = tpl.icon;
            return (
              <button
                key={tpl.id}
                onClick={() => handleApplyTemplate(tpl)}
                className="group text-left p-4 rounded-xl border border-slate-200 bg-white hover:border-blue-300 hover:shadow-md transition-all duration-200"
              >
                <div className="flex items-start gap-3">
                  <div className={`p-2.5 rounded-xl ${tpl.bgColor} shrink-0`}>
                    <Icon size={20} className={tpl.color} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium text-slate-800 text-sm truncate">{tpl.name}</h4>
                      {tpl.popular && (
                        <span className="text-[10px] font-medium text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded">
                          {t('reports.templates.popular')}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-1 line-clamp-2">{tpl.description}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </Section>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-6">
          <Section title={t('reports.settings.title')} subtitle={t('reports.settings.subtitle')} icon={SettingsIcon}>
            <FieldGroup label={t('reports.settings.reportType')}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {reportTypes.map((rt) => {
                  const active = reportType === rt.id;
                  return (
                    <button
                      key={rt.id}
                      onClick={() => setReportType(rt.id)}
                      className={`text-left p-3 rounded-lg border transition-all ${
                        active
                          ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-100'
                          : 'border-slate-200 bg-white hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className={`text-sm font-medium ${active ? 'text-blue-700' : 'text-slate-700'}`}>
                          {rt.label}
                        </span>
                        {active && <CheckCircle2 size={16} className="text-blue-600" />}
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5">{rt.description}</p>
                    </button>
                  );
                })}
              </div>
            </FieldGroup>

            <FieldGroup label={t('reports.settings.dataType')}>
              <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
                <button
                  onClick={() => setDataType('train_history')}
                  className={`px-3 py-2 text-sm ${
                    dataType === 'train_history' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {t('settings.data.history')}
                </button>
                <button
                  onClick={() => setDataType('predict_current')}
                  className={`px-3 py-2 text-sm ${
                    dataType === 'predict_current' ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {t('settings.data.current')}
                </button>
              </div>
            </FieldGroup>

            <FieldGroup label={t('reports.settings.dateRange')}>
              <div className="flex flex-wrap gap-2">
                {dateRangeOptions.map((d) => {
                  const active = dateRange === d.id;
                  return (
                    <button
                      key={d.id}
                      onClick={() => setDateRange(d.id)}
                      className={`px-3 py-2 text-sm rounded-lg border transition-all ${
                        active
                          ? 'bg-blue-600 border-blue-600 text-white shadow-sm shadow-blue-200'
                          : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
                      }`}
                    >
                      {d.label}
                    </button>
                  );
                })}
              </div>
              {dateRange === 'custom' && (
                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-xs text-slate-500 mb-1 block">{t('reports.dateRange.from')}</span>
                    <input
                      type="month"
                      value={customFrom}
                      onChange={(e) => setCustomFrom(e.target.value)}
                      className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-slate-500 mb-1 block">{t('reports.dateRange.to')}</span>
                    <input
                      type="month"
                      value={customTo}
                      onChange={(e) => setCustomTo(e.target.value)}
                      className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </label>
                </div>
              )}
            </FieldGroup>

            <FieldGroup label={t('reports.settings.format')}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {formatOptions.map((f) => {
                  const Icon = f.icon;
                  const active = reportFormat === f.id;
                  return (
                    <button
                      key={f.id}
                      onClick={() => setReportFormat(f.id)}
                      className={`p-3 rounded-lg border transition-all flex items-center gap-2 ${
                        active
                          ? `${f.color} ring-2 ring-offset-1 ring-blue-200`
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                      }`}
                    >
                      <Icon size={18} />
                      <span className="text-sm font-medium">{f.label}</span>
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-slate-400 mt-2">{t('reports.settings.formatHelp')}</p>
            </FieldGroup>

            <FieldGroup label={t('reports.settings.filter')} icon={Filter}>
              <MultiSelect
                title={t('reports.multiselect.group')}
                options={allDiseases}
                selected={selectedDiseases}
                onToggle={(v) =>
                  setSelectedDiseases((cur) =>
                    cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v],
                  )
                }
                onClear={() => setSelectedDiseases([])}
                clearAllLabel={t('reports.multiselect.clearAll')}
                emptyLabel={t('reports.multiselect.empty')}
              />
              <button
                onClick={loadDiseases}
                className="mt-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
              >
                <RefreshCcw size={12} /> {t('reports.settings.reloadGroups')}
              </button>
            </FieldGroup>

            <FieldGroup label={t('reports.settings.include')}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <ToggleRow label={t('reports.settings.includeTable')} checked={includeTable} onChange={setIncludeTable} />
                <ToggleRow label={t('reports.settings.includeSummary')} checked={includeSummary} onChange={setIncludeSummary} />
                <ToggleRow
                  label={t('reports.settings.includeRecommendation')}
                  checked={includeRecommendation}
                  onChange={setIncludeRecommendation}
                />
              </div>
            </FieldGroup>
          </Section>
        </div>

        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm sticky top-4">
            <div className="p-5 border-b border-slate-200">
              <h3 className="text-lg font-semibold text-slate-800">{t('reports.preview.title')}</h3>
              <p className="text-xs text-slate-400 mt-0.5">{t('reports.preview.subtitle')}</p>
            </div>
            <div className="p-5 space-y-3">
              <PreviewRow label={t('reports.preview.type')} value={reportTypeLabels[reportType]} />
              <PreviewRow
                label={t('reports.preview.data')}
                value={dataType === 'train_history' ? t('settings.data.history') : t('settings.data.current')}
              />
              <PreviewRow
                label={t('reports.preview.time')}
                value={
                  dateRange === 'custom' && customFrom && customTo
                    ? `${customFrom} → ${customTo}`
                    : dateRangeOptions.find((d) => d.id === dateRange)?.label ?? ''
                }
              />
              <PreviewRow
                label={t('reports.preview.format')}
                value={
                  <span className="flex items-center gap-1.5">
                    <selectedFormat.icon size={14} />
                    {selectedFormat.label}
                  </span>
                }
              />
              <PreviewRow
                label={t('reports.preview.disease')}
                value={selectedDiseases.length ? `${selectedDiseases.length} ${t('reports.preview.items')}` : t('reports.preview.all')}
              />
              <PreviewRow
                label={t('reports.preview.content')}
                value={
                  [
                    includeTable && t('reports.settings.includeTable'),
                    includeSummary && t('reports.settings.includeSummary'),
                    includeRecommendation && t('reports.settings.includeRecommendation'),
                  ]
                    .filter(Boolean)
                    .join(', ') || t('reports.preview.empty')
                }
              />
            </div>
            <div className="p-5 pt-0 space-y-2">
              <button
                onClick={handleGenerate}
                disabled={isGenerating}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium shadow-sm shadow-blue-200 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {isGenerating ? (
                  <>
                    <Clock size={16} className="animate-spin" />
                    {t('reports.preview.generating')}
                  </>
                ) : (
                  <>
                    <Download size={16} />
                    {t('reports.preview.generate')}
                  </>
                )}
              </button>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => window.print()}
                  className="flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-200 hover:bg-slate-50 rounded-lg text-sm text-slate-600 transition-colors"
                >
                  <Printer size={14} />
                  {t('reports.preview.printPage')}
                </button>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(window.location.href).catch(() => undefined);
                  }}
                  className="flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-200 hover:bg-slate-50 rounded-lg text-sm text-slate-600 transition-colors"
                >
                  <Share2 size={14} />
                  {t('reports.preview.copyLink')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <Section title={t('reports.history.title')} subtitle={t('reports.history.subtitle')} icon={Clock}>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              placeholder={t('common.search')}
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            <FilterChip active={historyFilter === 'all'} onClick={() => setHistoryFilter('all')}>
              {t('common.all')}
            </FilterChip>
            {(Object.keys(reportTypeLabels) as ReportType[]).map((type) => (
              <FilterChip
                key={type}
                active={historyFilter === type}
                onClick={() => setHistoryFilter(type)}
              >
                {reportTypeLabels[type]}
              </FilterChip>
            ))}
          </div>
          {history.length > 0 && (
            <button
              onClick={() => setHistory([])}
              className="text-xs text-slate-500 hover:text-red-600"
            >
              {t('reports.history.clear')}
            </button>
          )}
        </div>

        {filteredHistory.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-500 border border-dashed border-slate-200 rounded-xl">
            {t('reports.history.empty')}
          </div>
        ) : (
          <div className="overflow-x-auto -mx-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colName')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colType')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colFormat')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colCreator')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colTime')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colSize')}</th>
                  <th className="py-2.5 px-2 font-medium">{t('reports.history.colStatus')}</th>
                  <th className="py-2.5 px-2 font-medium text-right">{t('reports.history.colAction')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredHistory.map((r) => {
                  const fmt = formatOptions.find((f) => f.id === r.format)!;
                  const Icon = fmt.icon;
                  return (
                    <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="py-3 px-2">
                        <div className="flex items-center gap-2">
                          <Icon size={16} className={fmt.color.split(' ')[0]} />
                          <span className="font-medium text-slate-800">{r.name}</span>
                        </div>
                        {r.error && (
                          <p className="text-xs text-red-600 mt-1 break-words">{r.error}</p>
                        )}
                      </td>
                      <td className="py-3 px-2 text-slate-600">{reportTypeLabels[r.type]}</td>
                      <td className="py-3 px-2 text-slate-600 uppercase">{r.format}</td>
                      <td className="py-3 px-2 text-slate-600">{r.createdBy}</td>
                      <td className="py-3 px-2 text-slate-500 text-xs">{r.createdAt}</td>
                      <td className="py-3 px-2 text-slate-600">{r.size}</td>
                      <td className="py-3 px-2">
                        <span
                          className={`inline-flex items-center gap-1 text-xs border rounded-full px-2 py-0.5 ${statusStyles[r.status]}`}
                        >
                          {r.status === 'processing' && <Clock size={10} className="animate-spin" />}
                          {r.status === 'ready' && <CheckCircle2 size={10} />}
                          {r.status === 'failed' && <AlertTriangle size={10} />}
                          {statusLabels[r.status]}
                        </span>
                      </td>
                      <td className="py-3 px-2">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => handleDelete(r.id)}
                            className="p-1.5 text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

// ===== Helpers =====

interface PeriodBounds {
  from?: string;
  to?: string;
}

function aggregateByDisease(rows: api.MonthlyStat[]): Array<{ disease_group: string; case_count: number }> {
  const map = new Map<string, number>();
  for (const row of rows) {
    map.set(row.disease_group, (map.get(row.disease_group) ?? 0) + row.case_count);
  }
  return Array.from(map, ([disease_group, case_count]) => ({ disease_group, case_count }))
    .sort((a, b) => b.case_count - a.case_count);
}

function toPeriod(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function parsePeriod(period: string): Date {
  const [year, month] = period.split('-').map(Number);
  return new Date(year, (month || 1) - 1, 1);
}

function shiftPeriod(period: string, monthDelta: number): string {
  const date = parsePeriod(period);
  return toPeriod(new Date(date.getFullYear(), date.getMonth() + monthDelta, 1));
}

function getDateRangeBounds(
  rows: api.MonthlyStat[],
  range: DateRange,
  customFrom: string,
  customTo: string,
): PeriodBounds {
  if (range === 'custom') {
    return {
      from: customFrom || undefined,
      to: customTo || undefined,
    };
  }

  const periods = Array.from(new Set(rows.map((row) => row.period))).sort();
  const latest = periods[periods.length - 1];
  if (!latest) return {};

  if (range === '7d' || range === '30d') {
    return { from: latest, to: latest };
  }

  if (range === '90d') {
    return { from: shiftPeriod(latest, -2), to: latest };
  }

  const latestDate = parsePeriod(latest);
  const year = latestDate.getFullYear();

  if (range === 'quarter') {
    const quarterStartMonth = Math.floor(latestDate.getMonth() / 3) * 3;
    return {
      from: toPeriod(new Date(year, quarterStartMonth, 1)),
      to: toPeriod(new Date(year, quarterStartMonth + 2, 1)),
    };
  }

  if (range === 'year') {
    return { from: `${year}-01`, to: `${year}-12` };
  }

  return {};
}

function isPeriodInBounds(period: string, bounds: PeriodBounds): boolean {
  if (bounds.from && period < bounds.from) return false;
  if (bounds.to && period > bounds.to) return false;
  return true;
}

function filterByDateRange(
  rows: api.MonthlyStat[],
  range: DateRange,
  customFrom: string,
  customTo: string,
): api.MonthlyStat[] {
  if (rows.length === 0) return rows;
  const bounds = getDateRangeBounds(rows, range, customFrom, customTo);
  if (!bounds.from && !bounds.to) return rows;
  return rows.filter((row) => isPeriodInBounds(row.period, bounds));
}

function buildRecommendations(reportType: ReportType, bundle: ReportBundle): string[] {
  const recommendations: string[] = [];
  const totalRows = bundle.rows.length;

  if (totalRows === 0) {
    return [
      'Không có dữ liệu trong phạm vi đã chọn. Cần kiểm tra lại loại dữ liệu, khoảng thời gian hoặc dữ liệu import.',
    ];
  }

  if (reportType === 'forecast') {
    const highRisk = bundle.rows.filter((row) => row.risk_level === 'Cao').length;
    if (highRisk > 0) {
      recommendations.push(`Ưu tiên theo dõi ${highRisk} nhóm bệnh có mức nguy cơ cao trong kết quả dự báo.`);
    }
    recommendations.push('Đối chiếu kết quả dự báo với số ca thực tế sau khi có dữ liệu tháng mới.');
  } else if (reportType === 'seasonal') {
    const peak = bundle.rows
      .slice()
      .sort((a, b) => Number(b.case_count ?? 0) - Number(a.case_count ?? 0))[0];
    if (peak) {
      recommendations.push(`Tăng cường truyền thông phòng bệnh trong ${String(peak.season).toLowerCase()} vì đây là mùa có số ca cao nhất trong phạm vi báo cáo.`);
    }
  } else {
    const top = bundle.rows
      .slice()
      .sort((a, b) => Number(b.case_count ?? 0) - Number(a.case_count ?? 0))[0];
    if (top?.disease_group) {
      recommendations.push(`Ưu tiên theo dõi nhóm bệnh "${top.disease_group}" vì có số ca cao nhất trong báo cáo.`);
    }
  }

  recommendations.push('Sử dụng báo cáo như tài liệu tham khảo nghiệp vụ; không thay thế đánh giá chuyên môn của nhân viên y tế.');
  return recommendations;
}

// ===== UI components =====

function Section({
  title,
  subtitle,
  icon: Icon,
  children,
}: {
  title: string;
  subtitle?: string;
  icon?: typeof FileText;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl p-6 border border-slate-200 shadow-sm">
      <div className="flex items-start gap-3 mb-5">
        {Icon && (
          <div className="p-2 rounded-lg bg-blue-50">
            <Icon size={18} className="text-blue-600" />
          </div>
        )}
        <div>
          <h3 className="text-lg font-semibold text-slate-800 leading-tight">{title}</h3>
          {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function FieldGroup({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon?: typeof FileText;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5 last:mb-0">
      <div className="flex items-center gap-1.5 mb-2">
        {Icon && <Icon size={14} className="text-slate-500" />}
        <label className="text-sm font-medium text-slate-700">{label}</label>
      </div>
      {children}
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
  icon: typeof FileText;
  label: string;
  value: string;
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
          <p className="text-3xl font-bold text-slate-800 mt-1">{value}</p>
        </div>
        <div className={`p-3 rounded-xl ${iconBg}`}>
          <Icon className={iconColor} size={22} />
        </div>
      </div>
    </div>
  );
}

function MultiSelect({
  title,
  options,
  selected,
  onToggle,
  onClear,
  clearAllLabel,
  emptyLabel,
}: {
  title: string;
  options: string[];
  selected: string[];
  onToggle: (v: string) => void;
  onClear: () => void;
  clearAllLabel: string;
  emptyLabel: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-slate-200 rounded-lg bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-sm"
      >
        <span className="text-slate-700 font-medium">{title}</span>
        <div className="flex items-center gap-2">
          {selected.length > 0 && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
              {selected.length}
            </span>
          )}
          <ChevronDown
            size={16}
            className={`text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </div>
      </button>
      {open && (
        <div className="border-t border-slate-100 p-2">
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {selected.map((s) => (
                <span
                  key={s}
                  className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2 py-0.5"
                >
                  {s}
                  <button onClick={() => onToggle(s)} className="hover:text-blue-900">
                    <X size={10} />
                  </button>
                </span>
              ))}
              <button
                onClick={onClear}
                className="text-xs text-slate-500 hover:text-slate-700 underline"
              >
                {clearAllLabel}
              </button>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-1 max-h-72 overflow-auto">
            {options.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-slate-400 py-2 px-2 col-span-2">
                <Plus size={14} />
                {emptyLabel}
              </div>
            ) : (
              options.map((opt) => {
                const active = selected.includes(opt);
                return (
                  <button
                    key={opt}
                    onClick={() => onToggle(opt)}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left transition-colors ${
                      active ? 'bg-blue-50 text-blue-700' : 'hover:bg-slate-50 text-slate-600'
                    }`}
                  >
                    <span
                      className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                        active ? 'bg-blue-600 border-blue-600' : 'border-slate-300 bg-white'
                      }`}
                    >
                      {active && <CheckCircle2 size={10} className="text-white" />}
                    </span>
                    <span className="truncate">{opt}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 cursor-pointer transition-colors">
      <span className="text-sm text-slate-700">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors ${
          checked ? 'bg-blue-600' : 'bg-slate-300'
        }`}
        aria-pressed={checked}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </label>
  );
}

function PreviewRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800 font-medium text-right min-w-0 truncate">{value}</span>
    </div>
  );
}

function FilterChip({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs rounded-full border transition-all ${
        active
          ? 'bg-blue-600 border-blue-600 text-white'
          : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
      }`}
    >
      {children}
    </button>
  );
}
