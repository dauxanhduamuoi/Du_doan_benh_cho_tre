import {
  ArrowDown,
  ArrowUp,
  Baby,
  BookOpen,
  CalendarDays,
  CloudRain,
  CloudSun,
  Droplets,
  ExternalLink,
  Info,
  Loader2,
  Thermometer,
  UserRound,
  Wind,
} from 'lucide-react';
import type { WeatherAIDiseaseRanking } from '@/lib/api';
import {
  buildTier1DisplayGroups,
  type Tier1DisplayDirection,
  type Tier1DisplayGroup,
  type Tier1DisplayKind,
} from './tier1Presentation';

const DEFAULT_DISCLAIMER =
  'Thông tin này nhằm hỗ trợ theo dõi và phòng ngừa, không thay thế chẩn đoán của bác sĩ.';

type ResultsVariant = 'clinical' | 'parent';

const variantStyles: Record<ResultsVariant, { card: string; rank: string; tier1: string; tier2: string }> = {
  clinical: {
    card: 'border-slate-200 bg-white',
    rank: 'bg-sky-600 text-white',
    tier1: 'border-sky-100 bg-sky-50/70',
    tier2: 'border-teal-100 bg-teal-50/70',
  },
  parent: {
    card: 'border-white bg-white/80',
    rank: 'bg-gradient-to-br from-sky-500 to-teal-500 text-white',
    tier1: 'border-sky-100 bg-gradient-to-br from-sky-50 to-white',
    tier2: 'border-teal-100 bg-gradient-to-br from-teal-50 to-white',
  },
};

export function evidenceStatusLabel(status?: string | null): string | null {
  if (status === 'SUPPORTED') return 'Có cơ sở y khoa tương đối rõ';
  if (status === 'LIMITED_OR_INDIRECT') return 'Bằng chứng còn hạn chế / gián tiếp';
  return null;
}

export function isSafeSourceUrl(value: string): boolean {
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

const tier1Icons: Record<Tier1DisplayKind, typeof Info> = {
  AGE: Baby,
  GENDER: UserRound,
  TIME_OF_YEAR: CalendarDays,
  TEMPERATURE: Thermometer,
  HUMIDITY: Droplets,
  PRECIPITATION: CloudRain,
  WIND: Wind,
  WEATHER_CONDITION: CloudSun,
  OTHER: Info,
};

function directionEffect(direction: Exclude<Tier1DisplayDirection, 'MIXED'>): string {
  return direction === 'UP'
    ? 'Thông tin này đang làm điểm xếp hạng của nhóm bệnh tăng.'
    : 'Thông tin này đang làm điểm xếp hạng của nhóm bệnh giảm.';
}

function FactorList({
  title,
  groups,
  direction,
}: {
  title: string;
  groups: Tier1DisplayGroup[];
  direction: 'UP' | 'DOWN';
}) {
  if (groups.length === 0) return null;
  const isUp = direction === 'UP';
  const DirectionIcon = isUp ? ArrowUp : ArrowDown;
  return (
    <div>
      <p className={`mb-2 text-sm font-semibold ${isUp ? 'text-emerald-800' : 'text-indigo-800'}`}>
        {isUp ? '↑' : '↓'} {title}
      </p>
      <ul className="space-y-2">
        {groups.map((group) => {
          const ConceptIcon = tier1Icons[group.kind];
          return (
          <li
            key={group.key}
            className="flex items-start gap-2 rounded-xl border border-white/80 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
            data-testid={`tier1-group-${group.key}`}
          >
            <ConceptIcon
              size={17}
              aria-hidden="true"
              className={`mt-0.5 shrink-0 ${isUp ? 'text-emerald-600' : 'text-indigo-600'}`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-slate-800">{group.title}</p>
              {group.details.length > 0 ? (
                <ul className="mt-0.5 space-y-0.5 leading-5 text-slate-600">
                  {group.details.map((detail) => <li key={detail}>{detail}</li>)}
                </ul>
              ) : (
                <p className="mt-0.5 leading-5 text-slate-600">Điều kiện này đang được AI sử dụng để xếp hạng.</p>
              )}
              <p className={`mt-1 text-xs leading-5 ${isUp ? 'text-emerald-700' : 'text-indigo-700'}`}>
                <DirectionIcon size={13} aria-hidden="true" className="mr-1 inline" />
                {directionEffect(direction)}
              </p>
            </div>
          </li>
          );
        })}
      </ul>
    </div>
  );
}

function MixedFactorList({ groups }: { groups: Tier1DisplayGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div>
      <p className="mb-2 text-sm font-semibold text-amber-900">↕ Các yếu tố có tác động theo nhiều chiều</p>
      <ul className="space-y-2">
        {groups.map((group) => {
          const ConceptIcon = tier1Icons[group.kind];
          return (
            <li
              key={group.key}
              className="rounded-xl border border-amber-100 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
              data-testid={`tier1-group-${group.key}`}
            >
              <div className="flex items-start gap-2">
                <ConceptIcon size={17} aria-hidden="true" className="mt-0.5 shrink-0 text-amber-700" />
                <div className="min-w-0">
                  <p className="font-semibold text-slate-800">{group.title}</p>
                  {group.details.map((detail) => <p key={detail} className="mt-0.5 leading-5 text-slate-600">{detail}</p>)}
                  <p className="mt-1 leading-5 text-amber-900">
                    Nhiều đặc điểm trong nhóm này đang tác động đến thứ hạng theo các hướng khác nhau.
                  </p>
                  <ul className="mt-1 space-y-0.5 text-xs leading-5 text-slate-600">
                    {group.mixedDetails.map((detail, index) => (
                      <li key={`${detail.direction}-${detail.label}-${index}`}>
                        <span className={detail.direction === 'UP' ? 'text-emerald-700' : 'text-indigo-700'}>
                          {detail.direction === 'UP' ? '↑' : '↓'}
                        </span>{' '}
                        {detail.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function WeatherAIExplanationSections({
  prediction,
  variant = 'clinical',
}: {
  prediction: WeatherAIDiseaseRanking;
  variant?: ResultsVariant;
}) {
  const styles = variantStyles[variant];
  const tier1 = prediction.tier1;
  const tier2 = prediction.tier2;
  const evidenceLabel = evidenceStatusLabel(tier2.evidence_status);
  const safeSources = (tier2.sources ?? []).filter((source) => isSafeSourceUrl(source.url));
  const tier1Groups = buildTier1DisplayGroups(
    tier1.positive_factors ?? [],
    tier1.negative_factors ?? [],
  );
  const positiveGroups = tier1Groups.filter((group) => group.direction === 'UP');
  const negativeGroups = tier1Groups.filter((group) => group.direction === 'DOWN');
  const mixedGroups = tier1Groups.filter((group) => group.direction === 'MIXED');

  return (
    <div className="mt-4 space-y-3">
      {tier1.available && (
        <section className={`rounded-2xl border p-4 ${styles.tier1}`} aria-label="Giải thích xếp hạng của mô hình">
          <h4 className="text-sm font-bold text-slate-900">
            Vì sao AI xếp nhóm bệnh này ở vị trí #{prediction.rank}?
          </h4>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            AI dựa trên thông tin của trẻ và điều kiện thời tiết gần đây. Các yếu tố dưới đây đang ảnh hưởng đến thứ hạng của nhóm bệnh này.
          </p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <FactorList title="Đang làm nhóm bệnh này được xếp cao hơn" groups={positiveGroups} direction="UP" />
            <FactorList title="Đang làm nhóm bệnh này được xếp thấp hơn" groups={negativeGroups} direction="DOWN" />
          </div>
          {mixedGroups.length > 0 && <div className="mt-4"><MixedFactorList groups={mixedGroups} /></div>}
          <div className="mt-4 flex items-start gap-2 border-t border-sky-100 pt-3 text-xs leading-5 text-slate-600">
            <Info size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-sky-700" />
            <p>
              Đây là cách các thông tin đầu vào ảnh hưởng đến điểm xếp hạng của AI, không có nghĩa các yếu tố này trực tiếp gây ra bệnh.
            </p>
          </div>
        </section>
      )}

      {tier2.available && tier2.explanation_short_vi && (
        <section className={`rounded-2xl border p-4 ${styles.tier2}`} aria-label="Giải thích y khoa và dịch tễ học">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4 className="flex items-center gap-2 text-sm font-bold text-teal-950">
                <BookOpen size={17} aria-hidden="true" />
                Vì sao yếu tố thời tiết này có thể liên quan?
              </h4>
              <p className="mt-2 text-sm leading-6 text-slate-700">{tier2.explanation_short_vi}</p>
            </div>
            {evidenceLabel && (
              <span className="w-fit shrink-0 rounded-full border border-teal-200 bg-white px-3 py-1 text-xs font-semibold text-teal-800">
                {evidenceLabel}
              </span>
            )}
          </div>

          {tier2.limitations_vi && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
              <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
              <p><strong>Lưu ý:</strong> {tier2.limitations_vi}</p>
            </div>
          )}

          {safeSources.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-600">Nguồn tham khảo</p>
              <ul className="mt-2 space-y-2 text-sm">
                {safeSources.map((source, index) => (
                  <li key={`${source.url}-${index}`}>
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Mở nguồn tham khảo: ${source.title}`}
                      className="inline-flex items-start gap-1.5 font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-900"
                    >
                      <span>
                        {source.title} — {source.organization}{source.year ? ` (${source.year})` : ''}
                      </span>
                      <ExternalLink size={14} aria-hidden="true" className="mt-1 shrink-0" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export function WeatherAIDisclaimer({ disclaimer }: { disclaimer?: string | null }) {
  return (
    <aside
      className="mt-4 flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium leading-6 text-amber-950"
      aria-label="Lưu ý quan trọng"
    >
      <Info size={19} aria-hidden="true" className="mt-0.5 shrink-0" />
      <p>{disclaimer?.trim() || DEFAULT_DISCLAIMER}</p>
    </aside>
  );
}

export function WeatherAILoadingNotice() {
  return (
    <div role="status" aria-live="polite" className="mt-4 flex items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
      <Loader2 size={18} aria-hidden="true" className="animate-spin" />
      <span>Đang lấy thời tiết, xếp hạng nhóm bệnh và chuẩn bị giải thích…</span>
    </div>
  );
}

export function WeatherAIPredictionList({
  predictions,
  disclaimer,
  variant = 'clinical',
}: {
  predictions: WeatherAIDiseaseRanking[];
  disclaimer?: string | null;
  variant?: ResultsVariant;
}) {
  const styles = variantStyles[variant];
  return (
    <div>
      <div className="space-y-4" aria-label="Các nhóm bệnh được xếp hạng">
        {predictions.map((prediction) => (
          <article
            key={prediction.disease_id}
            className={`rounded-3xl border p-4 shadow-sm sm:p-5 ${styles.card}`}
            data-testid="weather-ai-prediction-card"
          >
            <div className="flex items-start gap-3">
              <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-base font-black shadow-sm ${styles.rank}`}>
                <span aria-label={`Xếp hạng ${prediction.rank}`}>#{prediction.rank}</span>
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-base font-bold leading-6 text-slate-900 sm:text-lg">{prediction.disease_name}</h3>
                <p className="mt-1 text-sm leading-5 text-slate-600">
                  {prediction.rank === 1
                    ? 'Được mô hình xếp là nhóm bệnh đáng lưu ý nhất trong bối cảnh hiện tại.'
                    : `Được xếp thứ ${prediction.rank} trong các nhóm bệnh đáng lưu ý ở bối cảnh hiện tại.`}
                </p>
              </div>
            </div>
            <WeatherAIExplanationSections prediction={prediction} variant={variant} />
          </article>
        ))}
      </div>
      <WeatherAIDisclaimer disclaimer={disclaimer} />
    </div>
  );
}
