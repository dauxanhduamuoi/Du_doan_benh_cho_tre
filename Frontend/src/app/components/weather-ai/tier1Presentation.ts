import type { WeatherAITier1Factor } from '@/lib/api';

export type Tier1DisplayDirection = 'UP' | 'DOWN' | 'MIXED';
export type Tier1DisplayKind =
  | 'AGE'
  | 'GENDER'
  | 'TIME_OF_YEAR'
  | 'TEMPERATURE'
  | 'HUMIDITY'
  | 'PRECIPITATION'
  | 'WIND'
  | 'WEATHER_CONDITION'
  | 'OTHER';

export interface Tier1DisplayGroup {
  key: string;
  kind: Tier1DisplayKind;
  title: string;
  direction: Tier1DisplayDirection;
  details: string[];
  mixedDetails: Array<{ direction: 'UP' | 'DOWN'; label: string }>;
  rawFactors: WeatherAITier1Factor[];
}

type WeatherFamily = Extract<
  Tier1DisplayKind,
  'TEMPERATURE' | 'HUMIDITY' | 'PRECIPITATION' | 'WIND' | 'WEATHER_CONDITION'
>;

function hasInputValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false;
  return typeof value !== 'number' || Number.isFinite(value);
}

function numericValue(factor: WeatherAITier1Factor | undefined): number | null {
  if (!factor || !hasInputValue(factor.input_value)) return null;
  const value = typeof factor.input_value === 'number'
    ? factor.input_value
    : Number(factor.input_value);
  return Number.isFinite(value) ? value : null;
}

function textValue(factor: WeatherAITier1Factor | undefined): string | null {
  if (!factor || !hasInputValue(factor.input_value)) return null;
  const value = String(factor.input_value).trim();
  return value || null;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value);
}

function formatAgeGroup(value: string): string {
  return value.replace(/(\d)\s*-\s*(\d)/g, '$1–$2');
}

function lowerFirst(value: string): string {
  return value ? value.charAt(0).toLocaleLowerCase('vi') + value.slice(1) : value;
}

function windowPhrase(window: WeatherAITier1Factor['window']): string {
  if (window === '3D') return 'trong 3 ngày gần đây';
  if (window === '7D') return 'trong 7 ngày gần đây';
  if (window === 'CURRENT') return 'hiện tại';
  return 'trong bối cảnh hiện tại';
}

function weatherFamily(factor: WeatherAITier1Factor): WeatherFamily | null {
  const feature = factor.feature.toLocaleLowerCase('en');
  const declared = String(factor.weather_factor ?? '').toLocaleUpperCase('en');
  if (feature.startsWith('temperature_') || declared === 'TEMPERATURE') return 'TEMPERATURE';
  if (feature.startsWith('humidity_') || declared === 'HUMIDITY') return 'HUMIDITY';
  if (
    feature.startsWith('rain_')
    || feature.startsWith('precipitation_')
    || declared === 'RAIN'
    || declared === 'PRECIPITATION'
  ) return 'PRECIPITATION';
  if (feature.startsWith('wind_speed_') || feature.startsWith('wind_gust_') || declared === 'WIND') return 'WIND';
  if (feature.startsWith('weather_code_') || declared === 'WEATHER_CONDITION') return 'WEATHER_CONDITION';
  return null;
}

function conceptForFactor(factor: WeatherAITier1Factor): { key: string; kind: Tier1DisplayKind } {
  if (factor.feature === 'age_group') return { key: 'demographic:age', kind: 'AGE' };
  if (factor.feature === 'gender') return { key: 'demographic:gender', kind: 'GENDER' };
  if (
    factor.category === 'SEASONAL_CALENDAR'
    || ['month', 'season', 'day_of_year_sin', 'day_of_year_cos'].includes(factor.feature)
  ) {
    return { key: 'seasonal:time-of-year', kind: 'TIME_OF_YEAR' };
  }
  const family = weatherFamily(factor);
  if (family) return { key: `weather:${family}:${factor.window}`, kind: family };
  return { key: `factor:${factor.feature}`, kind: 'OTHER' };
}

function titleFor(kind: Tier1DisplayKind, factors: WeatherAITier1Factor[]): string {
  const phrase = windowPhrase(factors[0]?.window ?? 'NONE');
  if (kind === 'AGE') return 'Độ tuổi';
  if (kind === 'GENDER') return 'Giới tính';
  if (kind === 'TIME_OF_YEAR') return 'Thời điểm trong năm';
  if (kind === 'TEMPERATURE') return `Nhiệt độ ${phrase}`;
  if (kind === 'HUMIDITY') return `Độ ẩm ${phrase}`;
  if (kind === 'PRECIPITATION') return `Mưa ${phrase}`;
  if (kind === 'WIND') return `Gió ${phrase}`;
  if (kind === 'WEATHER_CONDITION') return `Tình trạng thời tiết ${phrase}`;
  return factors[0]?.label_vi || 'Thông tin đầu vào';
}

function factorByFeature(
  factors: WeatherAITier1Factor[],
  predicate: (feature: string) => boolean,
): WeatherAITier1Factor | undefined {
  return factors.find((factor) => predicate(factor.feature));
}

function temperatureOrHumidityDetails(
  kind: 'TEMPERATURE' | 'HUMIDITY',
  factors: WeatherAITier1Factor[],
): string[] {
  const phrase = windowPhrase(factors[0]?.window ?? 'NONE');
  const unit = kind === 'TEMPERATURE' ? '°C' : '%';
  const noun = kind === 'TEMPERATURE' ? 'Nhiệt độ' : 'Độ ẩm';
  const min = numericValue(factorByFeature(factors, (feature) => feature.includes('_min_')));
  const max = numericValue(factorByFeature(factors, (feature) => feature.includes('_max_')));
  const mean = numericValue(factorByFeature(factors, (feature) => feature.includes('_mean_') || feature.endsWith('_mean')));
  const details: string[] = [];
  if (min !== null && max !== null) {
    details.push(`${noun} ${phrase}: ${formatNumber(min)}–${formatNumber(max)}${unit}`);
  }
  if (mean !== null) {
    details.push(`${noun} trung bình ${phrase}: ${formatNumber(mean)}${unit}`);
  } else if (min !== null && max === null) {
    details.push(`${noun} thấp nhất ${phrase}: ${formatNumber(min)}${unit}`);
  } else if (max !== null && min === null) {
    details.push(`${noun} cao nhất ${phrase}: ${formatNumber(max)}${unit}`);
  }
  return details;
}

function windDetails(factors: WeatherAITier1Factor[]): string[] {
  const phrase = windowPhrase(factors[0]?.window ?? 'NONE');
  const definitions: Array<[string, (feature: string) => boolean]> = [
    [`Gió trung bình ${phrase}`, (feature) => feature.includes('wind_speed_mean')],
    [`Gió mạnh nhất ${phrase}`, (feature) => feature.includes('wind_speed_max')],
    [`Gió giật mạnh nhất ${phrase}`, (feature) => feature.includes('wind_gust_max')],
  ];
  return definitions.flatMap(([label, predicate]) => {
    const value = numericValue(factorByFeature(factors, predicate));
    return value === null ? [] : [`${label}: ${formatNumber(value)} km/h`];
  });
}

function precipitationDetails(factors: WeatherAITier1Factor[]): string[] {
  const phrase = windowPhrase(factors[0]?.window ?? 'NONE');
  const details: string[] = [];
  const definitions: Array<[string, (feature: string) => boolean, string]> = [
    [`Tổng lượng mưa ${phrase}`, (feature) => feature.startsWith('rain_sum_'), ' mm'],
    [`Tổng lượng giáng thủy ${phrase}`, (feature) => feature.startsWith('precipitation_sum_'), ' mm'],
    [`Ngày mưa nhiều nhất ${phrase}`, (feature) => feature.startsWith('rain_max_daily_'), ' mm'],
  ];
  definitions.forEach(([label, predicate, unit]) => {
    const value = numericValue(factorByFeature(factors, predicate));
    if (value !== null) details.push(`${label}: ${formatNumber(value)}${unit}`);
  });
  const rainDaysFactor = factorByFeature(factors, (feature) => feature.startsWith('rain_days_'));
  const rainDays = numericValue(rainDaysFactor);
  if (rainDays !== null) {
    const denominator = rainDaysFactor?.window === '3D' ? 3 : rainDaysFactor?.window === '7D' ? 7 : null;
    details.push(
      denominator
        ? `Có mưa trong ${formatNumber(rainDays)}/${denominator} ngày gần đây`
        : `Số ngày có mưa: ${formatNumber(rainDays)}`,
    );
  }
  const currentRain = numericValue(factorByFeature(factors, (feature) => feature === 'rain_day_current'));
  if (currentRain !== null) details.push(currentRain > 0 ? 'Hôm nay có ghi nhận mưa' : 'Hôm nay chưa ghi nhận mưa');
  return details;
}

function timeOfYearDetails(factors: WeatherAITier1Factor[]): string[] {
  const month = numericValue(factorByFeature(factors, (feature) => feature === 'month'));
  const season = textValue(factorByFeature(factors, (feature) => feature === 'season'));
  if (month !== null && Number.isInteger(month) && month >= 1 && month <= 12 && season) {
    return [`Hiện tại là tháng ${month}, thuộc ${lowerFirst(season)}.`];
  }
  if (month !== null && Number.isInteger(month) && month >= 1 && month <= 12) {
    return [`Hiện tại là tháng ${month}.`];
  }
  if (season) return [`Hiện tại thuộc ${lowerFirst(season)}.`];
  return [];
}

function detailsFor(kind: Tier1DisplayKind, factors: WeatherAITier1Factor[]): string[] {
  if (kind === 'AGE') {
    const value = textValue(factors[0]);
    return value ? [`Trẻ thuộc nhóm ${formatAgeGroup(value)}`] : [];
  }
  if (kind === 'GENDER') {
    const value = textValue(factors[0]);
    return value ? [`Giới tính: ${value}`] : [];
  }
  if (kind === 'TIME_OF_YEAR') return timeOfYearDetails(factors);
  if (kind === 'TEMPERATURE' || kind === 'HUMIDITY') {
    return temperatureOrHumidityDetails(kind, factors);
  }
  if (kind === 'WIND') return windDetails(factors);
  if (kind === 'PRECIPITATION') return precipitationDetails(factors);
  if (kind === 'WEATHER_CONDITION') return [];
  const value = textValue(factors[0]);
  return value ? [`${factors[0].label_vi}: ${value}`] : [];
}

function mixedFactorLabel(factor: WeatherAITier1Factor): string {
  const phrase = windowPhrase(factor.window);
  if (factor.feature.includes('temperature_min')) return `Nhiệt độ thấp nhất ${phrase}`;
  if (factor.feature.includes('temperature_max')) return `Nhiệt độ cao nhất ${phrase}`;
  if (factor.feature.includes('temperature_mean')) return `Nhiệt độ trung bình ${phrase}`;
  if (factor.feature.includes('humidity_min')) return `Độ ẩm thấp nhất ${phrase}`;
  if (factor.feature.includes('humidity_max')) return `Độ ẩm cao nhất ${phrase}`;
  if (factor.feature.includes('humidity_mean')) return `Độ ẩm trung bình ${phrase}`;
  if (factor.feature.includes('wind_speed_mean')) return `Gió trung bình ${phrase}`;
  if (factor.feature.includes('wind_speed_max')) return `Gió mạnh nhất ${phrase}`;
  if (factor.feature.includes('wind_gust_max')) return `Gió giật mạnh nhất ${phrase}`;
  if (factor.feature === 'age_group') return 'Độ tuổi của trẻ';
  if (factor.feature === 'gender') return 'Giới tính của trẻ';
  if (['month', 'season', 'day_of_year_sin', 'day_of_year_cos'].includes(factor.feature)) {
    return 'Thời điểm trong năm';
  }
  return factor.label_vi || 'Thông tin đầu vào';
}

export function buildTier1DisplayGroups(
  positiveFactors: WeatherAITier1Factor[] = [],
  negativeFactors: WeatherAITier1Factor[] = [],
): Tier1DisplayGroup[] {
  const rawFactors = [...positiveFactors, ...negativeFactors];
  const grouped = new Map<string, { kind: Tier1DisplayKind; factors: WeatherAITier1Factor[] }>();
  rawFactors.forEach((factor) => {
    const concept = conceptForFactor(factor);
    const existing = grouped.get(concept.key);
    if (existing) existing.factors.push(factor);
    else grouped.set(concept.key, { kind: concept.kind, factors: [factor] });
  });

  return [...grouped.entries()].map(([key, group]) => {
    const directions = new Set(group.factors.map((factor) => factor.direction));
    const direction: Tier1DisplayDirection = directions.size === 1
      ? group.factors[0].direction
      : 'MIXED';
    return {
      key,
      kind: group.kind,
      title: titleFor(group.kind, group.factors),
      direction,
      details: detailsFor(group.kind, group.factors),
      mixedDetails: direction === 'MIXED'
        ? group.factors.map((factor) => ({
            direction: factor.direction,
            label: mixedFactorLabel(factor),
          }))
        : [],
      rawFactors: group.factors,
    };
  });
}
