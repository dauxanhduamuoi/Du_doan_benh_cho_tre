import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type * as api from '@/lib/api';
import { splitDiseaseLabel } from '@/lib/disease';
import { WeatherAIExplanationSections } from '../weather-ai/WeatherAIResults';
import { buildTier1Summary } from '../weather-ai/tier1Presentation';
import { TrustedReferenceSection } from './TrustedReferenceSection';

const RISK_STYLE: Record<string, string> = {
  Cao: 'text-red-800',
  'Trung bình': 'text-amber-800',
  Thấp: 'text-slate-600',
};

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
  trustedReferences: api.TrustedReferenceItem[];
};

function useVietnameseT(): TFunction {
  const { i18n } = useTranslation();
  return i18n.getFixedT('vi') as TFunction;
}

function riskStyle(level: string) {
  return RISK_STYLE[level] ?? 'text-slate-600';
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
  emptyText,
}: {
  title: string;
  rows: string[];
  emptyText?: string;
}) {
  const t = useVietnameseT();
  return (
    <section>
      <h4 className="flex items-center gap-2 text-sm font-semibold">
        {title}
      </h4>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm leading-6 text-slate-500">{emptyText ?? t('parent.risk.noGuideData')}</p>
      ) : (
        <ul className="mt-2 list-disc space-y-2 pl-4 [overflow-wrap:anywhere] text-sm leading-6 text-slate-700">
          {rows.slice(0, 2).map((row, index) => (
            <li key={`${index}-${row}`}>
              <span>{row}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 2 && (
        <details className="mt-2 text-sm text-slate-600">
          <summary className="cursor-pointer rounded-md py-2 font-medium text-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">
            Xem thêm: {title.toLocaleLowerCase('vi-VN')}
          </summary>
          <ul className="mt-2 list-disc space-y-2 pl-4 [overflow-wrap:anywhere] leading-6">
            {rows.slice(2).map((row, index) => <li key={`${index}-${row}`}>{row}</li>)}
          </ul>
        </details>
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
    <div className="grid gap-5 sm:grid-cols-2" aria-label="Hướng dẫn dành cho phụ huynh">
      <GuidanceList
        title={t('parent.risk.commonSymptoms')}
        rows={symptoms}
        emptyText="Hiện chưa có thông tin triệu chứng cho nhóm bệnh này."
      />
      <GuidanceList
        title="Phụ huynh nên làm gì"
        rows={prevention}
      />
    </div>
  );
}

function DangerSignsAlert({ warning }: { warning: string }) {
  return (
    <section
      className="border-l-2 border-red-200 pl-4 text-red-900"
      role="note"
      aria-label="Khi nào cần đưa trẻ đi khám"
    >
      <h4 className="flex items-center gap-2 text-sm font-semibold">
        <AlertTriangle size={16} aria-hidden="true" className="shrink-0 text-red-700" />
        Khi nào cần đưa trẻ đi khám?
      </h4>
      <p className="mt-2 [overflow-wrap:anywhere] text-sm leading-6 text-slate-700">{warning}</p>
    </section>
  );
}

export function ParentDiseaseCard({
  row,
  featured = false,
  anchorDate,
}: {
  row: ParentDiseaseCardRow;
  featured?: boolean;
  anchorDate?: string | null;
}) {
  const t = useVietnameseT();
  const label = splitDiseaseLabel(row.disease_name).vi;
  const areaPeriod = formatPeriodRange(row.localPeriodFrom, row.localPeriodTo, t);
  const quickSummary = row.tier1.available ? buildTier1Summary(label) : (
    row.rank === 1
      ? 'Đây là nhóm bệnh được AI xếp cần lưu ý nhất trong bối cảnh hiện tại.'
      : `Đây là nhóm bệnh được AI xếp ở vị trí thứ ${row.rank} trong bối cảnh hiện tại.`
  );

  return (
    <article
      className={`min-w-0 rounded-xl border border-slate-200 bg-white ${featured ? 'border-l-2 border-l-teal-600' : ''}`}
      data-testid="parent-disease-card"
    >
      <div className="p-4 sm:p-5 lg:p-6">
        <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-semibold tabular-nums ${featured ? 'bg-teal-50 text-teal-800' : 'bg-slate-100 text-slate-600'}`}>
              <span aria-label={`Xếp hạng ${row.rank}`}>#{row.rank}</span>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="min-w-0 [overflow-wrap:anywhere] text-lg font-semibold leading-6 text-slate-950 sm:text-xl">
                  {label}
                </h3>
                {featured && (
                  <span className="text-sm text-teal-800">
                    Đáng lưu ý nhất
                  </span>
                )}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                <span className="text-slate-600">
                  {t('parent.risk.areaCases', {
                    cases: row.localCases === null
                      ? t('parent.risk.noLocalData')
                      : t('parent.risk.caseCount', { count: row.localCases.toLocaleString('vi-VN') }),
                    period: areaPeriod,
                  })}
                </span>
                {row.report_group_code && (
                  <span className="text-slate-500">
                    {row.report_group_code}
                  </span>
                )}
              </div>
            </div>
          </div>
          {row.localRisk && (
            <span className={`w-fit text-sm font-medium ${riskStyle(row.localRisk)}`}>
              Dữ liệu khu vực: {riskText(row.localRisk, t)}
            </span>
          )}
        </header>

        <section className="mt-4" aria-label="Tóm tắt nhanh">
          <p className="text-sm text-slate-500">Điểm xếp hạng mô hình: <span className="font-medium tabular-nums text-slate-700">{row.ranking_score.toLocaleString('vi-VN', { maximumSignificantDigits: 6 })}</span></p>
          <p className="mt-2 [overflow-wrap:anywhere] text-sm leading-6 text-slate-600">{quickSummary}</p>
        </section>

        <div className="mt-5 min-w-0 space-y-5">
          <aside className="min-w-0 space-y-5 border-t border-slate-200 pt-5" aria-label="Thông tin chăm sóc và đi khám">
            <ParentAdviceSection
              symptoms={row.knowledge.symptoms}
              prevention={row.knowledge.prevention}
            />
            <DangerSignsAlert warning={row.knowledge.warning} />
          </aside>
          {row.tier1.available && (
            <details className="border-t border-slate-200 pt-3">
              <summary className="cursor-pointer rounded-md py-2 text-sm font-medium text-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">
                Xem chi tiết giải thích mô hình
              </summary>
              <div className="mt-3">
                <WeatherAIExplanationSections prediction={row} variant="parent" showLegacyTier2={false} anchorDate={anchorDate} />
              </div>
            </details>
          )}
          <TrustedReferenceSection items={row.trustedReferences} collapsible />
        </div>
      </div>
    </article>
  );
}
