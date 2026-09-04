import type { ReactNode } from 'react';
import {
  Activity,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Siren,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type * as api from '@/lib/api';
import { splitDiseaseLabel } from '@/lib/disease';
import {
  PublishedMedicalKnowledgeSections,
  WeatherAIExplanationSections,
} from '../weather-ai/WeatherAIResults';

const RISK_STYLE: Record<string, string> = {
  Cao: 'border-rose-200 bg-rose-50 text-rose-700',
  'Trung bình': 'border-amber-200 bg-amber-50 text-amber-700',
  Thấp: 'border-emerald-200 bg-emerald-50 text-emerald-700',
};

const CARD_ACCENTS = [
  'from-sky-500 to-cyan-400',
  'from-rose-500 to-orange-400',
  'from-teal-500 to-emerald-400',
  'from-amber-500 to-orange-400',
  'from-fuchsia-500 to-violet-400',
] as const;

export type ParentDiseaseCardRow = api.WeatherAIDiseaseRanking & {
  localCases: number | null;
  localRisk: string | null;
  localPeriodFrom: string | null;
  localPeriodTo: string | null;
  knowledge: {
    symptoms: string[];
    warning: string;
    prevention: string[];
    source: string;
  };
  publishedMedicalKnowledge: api.PublishedMedicalKnowledgeItem[];
};

function useVietnameseT(): TFunction {
  const { i18n } = useTranslation();
  return i18n.getFixedT('vi') as TFunction;
}

function riskStyle(level: string) {
  return RISK_STYLE[level] ?? 'border-sky-200 bg-sky-50 text-sky-700';
}

function riskText(level: string, t: TFunction) {
  if (level === 'Cao') return t('common.high');
  if (level === 'Trung bình' || level === 'Trung binh') return t('common.medium');
  if (level === 'Thấp' || level === 'Thap') return t('common.low');
  return level;
}

function formatPeriodRange(
  from: string | null | undefined,
  to: string | null | undefined,
  t: TFunction,
) {
  if (from && to && from !== to) return t('parent.period.range', { from, to });
  if (from || to) return from ?? to;
  return t('parent.period.currentImported');
}

function GuidanceList({
  title,
  rows,
  icon,
  tone,
}: {
  title: string;
  rows: string[];
  icon: ReactNode;
  tone: 'sky' | 'teal';
}) {
  const t = useVietnameseT();
  const styles = tone === 'teal'
    ? 'border-teal-100 bg-teal-50/70 text-teal-900'
    : 'border-sky-100 bg-sky-50/70 text-sky-900';
  return (
    <section className={`rounded-2xl border p-3.5 ${styles}`}>
      <h4 className="flex items-center gap-2 text-sm font-extrabold">
        {icon}
        {title}
      </h4>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs leading-5 text-slate-500">{t('parent.risk.noGuideData')}</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs font-medium leading-5 text-slate-700">
          {rows.slice(0, 4).map((row) => (
            <li key={row} className="flex gap-2">
              <CheckCircle2 size={14} aria-hidden="true" className="mt-0.5 shrink-0 text-teal-600" />
              <span>{row}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ParentAdviceSection({
  symptoms,
  prevention,
}: {
  symptoms: string[];
  prevention: string[];
}) {
  const t = useVietnameseT();
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1" aria-label="Hướng dẫn dành cho phụ huynh">
      <GuidanceList
        title="Phụ huynh nên làm gì"
        rows={prevention}
        tone="teal"
        icon={<ClipboardCheck size={17} aria-hidden="true" />}
      />
      <GuidanceList
        title={t('parent.risk.commonSymptoms')}
        rows={symptoms}
        tone="sky"
        icon={<Activity size={17} aria-hidden="true" />}
      />
    </div>
  );
}

function DangerSignsAlert({ warning }: { warning: string }) {
  return (
    <section
      className="rounded-2xl border border-rose-200 bg-gradient-to-br from-rose-50 to-amber-50 p-3.5 text-rose-950"
      role="note"
      aria-label="Khi nào cần đưa trẻ đi khám"
    >
      <h4 className="flex items-center gap-2 text-sm font-extrabold">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-rose-600 shadow-sm">
          <Siren size={16} aria-hidden="true" />
        </span>
        Khi nào cần đưa trẻ đi khám?
      </h4>
      <p className="mt-2 text-xs font-medium leading-5 text-slate-700">{warning}</p>
    </section>
  );
}

function ExpandableExplanation({ children }: { children: ReactNode }) {
  return (
    <details className="group rounded-2xl border border-teal-100 bg-white/80 shadow-sm">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-extrabold text-teal-950 marker:content-none">
        <span className="flex items-center gap-2">
          <BookOpen size={17} aria-hidden="true" className="text-teal-600" />
          Giải thích y khoa chi tiết
        </span>
        <span className="inline-flex items-center gap-1 text-xs font-bold text-teal-700">
          <span className="group-open:hidden">Mở rộng</span>
          <span className="hidden group-open:inline">Thu gọn</span>
          <ChevronDown size={16} aria-hidden="true" className="transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-teal-100 px-3 pb-3">{children}</div>
    </details>
  );
}

export function ParentDiseaseCard({
  row,
  index,
  featured = false,
  tier2Loading = false,
}: {
  row: ParentDiseaseCardRow;
  index: number;
  featured?: boolean;
  tier2Loading?: boolean;
}) {
  const t = useVietnameseT();
  const label = splitDiseaseLabel(row.disease_name).vi;
  const areaPeriod = formatPeriodRange(row.localPeriodFrom, row.localPeriodTo, t);
  const quickSummary = row.tier1.summary_vi || (
    row.rank === 1
      ? 'Đây là nhóm bệnh được AI xếp cần lưu ý nhất trong bối cảnh hiện tại.'
      : `Đây là nhóm bệnh được AI xếp ở vị trí thứ ${row.rank} trong bối cảnh hiện tại.`
  );
  const accent = CARD_ACCENTS[index % CARD_ACCENTS.length];

  return (
    <article
      className={`relative overflow-hidden rounded-[26px] border bg-white shadow-sm transition-shadow hover:shadow-md ${featured ? 'border-sky-200' : 'border-slate-200'}`}
      data-testid="parent-disease-card"
    >
      <div className={`h-1.5 bg-gradient-to-r ${accent}`} />
      <div className="p-4 sm:p-5 lg:p-6">
        <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 gap-3.5">
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-sm font-black text-white shadow-sm ${accent}`}>
              <span aria-label={`Xếp hạng ${row.rank}`}>#{row.rank}</span>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className={`${featured ? 'text-xl sm:text-2xl' : 'text-lg sm:text-xl'} font-black leading-tight text-slate-950`}>
                  {label}
                </h3>
                {featured && (
                  <span className="rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-extrabold text-sky-700">
                    Đáng lưu ý nhất
                  </span>
                )}
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-[11px] font-bold sm:text-xs">
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">
                  {t('parent.risk.areaCases', {
                    cases: row.localCases === null
                      ? t('parent.risk.noLocalData')
                      : t('parent.risk.caseCount', { count: row.localCases.toLocaleString('vi-VN') }),
                    period: areaPeriod,
                  })}
                </span>
                {row.report_group_code && (
                  <span className="rounded-full border border-violet-100 bg-violet-50 px-2.5 py-1 text-violet-700">
                    {row.report_group_code}
                  </span>
                )}
              </div>
            </div>
          </div>
          {row.localRisk && (
            <span className={`w-fit shrink-0 rounded-full border px-3 py-1.5 text-xs font-black ${riskStyle(row.localRisk)}`}>
              Dữ liệu khu vực: {riskText(row.localRisk, t)}
            </span>
          )}
        </header>

        <section className="mt-4 rounded-2xl border border-slate-100 bg-slate-50/80 px-4 py-3" aria-label="Tóm tắt nhanh">
          <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Tóm tắt nhanh</p>
          <p className="mt-1 text-sm font-medium leading-6 text-slate-700">{quickSummary}</p>
        </section>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(280px,0.75fr)] xl:items-start">
          <div className="min-w-0 space-y-3">
            <WeatherAIExplanationSections prediction={row} variant="parent" showLegacyTier2={false} />
            {row.publishedMedicalKnowledge.length > 0 ? (
              <ExpandableExplanation>
                <PublishedMedicalKnowledgeSections items={row.publishedMedicalKnowledge} />
              </ExpandableExplanation>
            ) : (
              <PublishedMedicalKnowledgeSections items={[]} loading={tier2Loading} />
            )}
          </div>

          <aside className="min-w-0 space-y-3" aria-label="Thông tin chăm sóc và đi khám">
            <ParentAdviceSection
              symptoms={row.knowledge.symptoms}
              prevention={row.knowledge.prevention}
            />
            <DangerSignsAlert warning={row.knowledge.warning} />
          </aside>
        </div>
      </div>
    </article>
  );
}
