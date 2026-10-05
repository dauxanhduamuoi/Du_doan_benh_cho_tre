import type { WeatherAITier1Factor } from '@/lib/api';
import { TIER1_FEATURE_DEFINITIONS, type Tier1FeatureFamily } from './tier1FeatureDefinitions';

export type Tier1DisplayDirection = 'UP' | 'DOWN' | 'MIXED';
export type Tier1DisplayKind = Tier1FeatureFamily | 'OTHER';

export interface Tier1DisplayGroup {
  key: string;
  kind: Tier1DisplayKind;
  title: string;
  direction: Tier1DisplayDirection;
  details: string[];
  mixedDetails: Array<{ direction: 'UP' | 'DOWN'; label: string }>;
  rawFactors: WeatherAITier1Factor[];
}

export interface Tier1PresentationContext {
  diseaseName?: string;
  anchorDate?: string | null;
}

export const MODEL_EXPLANATION_DISCLAIMER =
  'Phần này giải thích cách các đặc trưng đóng góp vào kết quả của mô hình. Nó không chứng minh nguyên nhân gây bệnh và không phải xác suất mắc bệnh của trẻ.';

function displayDate(anchorDate?: string | null): string | null {
  if (!anchorDate || !/^\d{4}-\d{2}-\d{2}$/.test(anchorDate)) return null;
  const date = new Date(`${anchorDate}T00:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== anchorDate) return null;
  const [year, month, day] = anchorDate.split('-');
  return `${day}/${month}/${year}`;
}

function windowDescription(window: WeatherAITier1Factor['window'], anchorDate?: string | null): string {
  const date = displayDate(anchorDate);
  if (window === 'CURRENT') return date ? `ngày dữ liệu ${date}` : 'ngày dữ liệu (chưa cung cấp ngày)';
  if (window === '3D' || window === '7D') {
    const days = window === '3D' ? 3 : 7;
    return date ? `${days} ngày kết thúc ngày ${date}` : `${days} ngày (chưa cung cấp ngày kết thúc)`;
  }
  return 'bối cảnh đầu vào của mô hình';
}

function textValue(value: unknown): string | null {
  if (typeof value === 'number') {
    return Number.isFinite(value)
      ? new Intl.NumberFormat('vi-VN', { maximumSignificantDigits: 21, useGrouping: false }).format(value)
      : null;
  }
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numericValue(value: unknown): string | null {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null;
  return textValue(Number(value));
}

function directionSentence(direction: 'UP' | 'DOWN', diseaseName?: string): string {
  const disease = diseaseName?.trim() ? `nhóm ${diseaseName.trim()}` : 'nhóm bệnh này';
  return `Đặc trưng này đóng góp theo chiều làm ${direction === 'UP' ? 'tăng' : 'giảm'} điểm của ${disease} trong mô hình, so với mức nền của model.`;
}

export function formatTier1Factor(factor: WeatherAITier1Factor, context: Tier1PresentationContext = {}): string {
  const definition = TIER1_FEATURE_DEFINITIONS[factor.feature];
  const date = displayDate(context.anchorDate);
  const description = definition?.descriptionVi || (factor.label_vi !== factor.feature ? factor.label_vi : 'Đặc trưng đầu vào');
  const categorical = definition?.statistic === 'CATEGORY';
  const value = definition && !categorical ? numericValue(factor.input_value) : textValue(factor.input_value);
  const window = windowDescription(definition?.window ?? factor.window, context.anchorDate);
  let inputSentence: string;
  if (value === null) {
    inputSentence = `${description}: chưa có giá trị đầu vào để hiển thị.`;
  } else if (definition?.family === 'AGE') {
    inputSentence = `Nhóm tuổi được đưa vào mô hình là ${value}.`;
  } else if (definition?.family === 'GENDER') {
    inputSentence = `Giới tính được đưa vào mô hình là ${value}.`;
  } else if (factor.feature === 'month') {
    inputSentence = date ? `Ngày dữ liệu ${date} thuộc tháng ${value}.` : `Tháng được đưa vào mô hình là ${value} (chưa cung cấp ngày dữ liệu).`;
  } else if (factor.feature === 'season') {
    inputSentence = date
      ? `Theo quy ước mùa được sử dụng trong mô hình, ngày dữ liệu ${date} thuộc ${value}.`
      : `Theo quy ước mùa được sử dụng trong mô hình, mùa đầu vào là ${value} (chưa cung cấp ngày dữ liệu).`;
  } else if (definition?.statistic === 'SIN' || definition?.statistic === 'COS') {
    inputSentence = `${description}${date ? ` của ngày ${date}` : ' (chưa cung cấp ngày dữ liệu)'} có giá trị đầu vào ${value}.`;
  } else if (definition?.statistic === 'RAIN_DAYS') {
    inputSentence = `Trong cửa sổ ${window}, có ${value} ngày có lượng mưa lớn hơn 0 theo dữ liệu đầu vào.`;
  } else if (definition?.statistic === 'RAIN_DAY') {
    inputSentence = `${description} trong ${window} có giá trị đầu vào ${value} (1: có; 0: không, theo dữ liệu đầu vào).`;
  } else if (definition?.statistic === 'MAX_DAILY') {
    inputSentence = `${description} của cửa sổ ${window} là ${value} mm.`;
  } else if (definition) {
    const unit = definition.unit === '°C' || definition.unit === '%' ? definition.unit : definition.unit ? ` ${definition.unit}` : '';
    inputSentence = `${description} trong ${window} là ${value}${unit}.`;
  } else {
    inputSentence = `${description}: giá trị đầu vào là ${value}.`;
  }
  return `${inputSentence} ${directionSentence(factor.direction, context.diseaseName)}`;
}

export function buildTier1Summary(diseaseName: string): string {
  return `Các đặc trưng được chọn dưới đây mô tả đóng góp vào điểm của nhóm ${diseaseName} trong mô hình, so với mức nền của model.`;
}

const familyTitles: Record<Tier1DisplayKind, string> = {
  AGE: 'Nhóm tuổi', GENDER: 'Giới tính', TIME_OF_YEAR: 'Thời điểm trong năm',
  TEMPERATURE: 'Nhiệt độ', HUMIDITY: 'Độ ẩm', PRECIPITATION: 'Mưa / giáng thủy',
  WIND: 'Gió', WEATHER_CONDITION: 'Trạng thái thời tiết', OTHER: 'Thông tin đầu vào',
};

export function buildTier1DisplayGroups(
  positiveFactors: WeatherAITier1Factor[] = [],
  negativeFactors: WeatherAITier1Factor[] = [],
  context: Tier1PresentationContext = {},
): Tier1DisplayGroup[] {
  const grouped = new Map<string, { kind: Tier1DisplayKind; window: WeatherAITier1Factor['window']; factors: WeatherAITier1Factor[] }>();
  for (const factor of [...positiveFactors, ...negativeFactors]) {
    const definition = TIER1_FEATURE_DEFINITIONS[factor.feature];
    const kind = definition?.family ?? 'OTHER';
    const window = definition?.window ?? factor.window;
    const key = kind === 'AGE' ? 'demographic:age' : kind === 'GENDER' ? 'demographic:gender'
      : kind === 'TIME_OF_YEAR' ? 'seasonal:time-of-year' : kind === 'OTHER' ? `factor:${factor.feature}` : `weather:${kind}:${window}`;
    const existing = grouped.get(key);
    if (existing) existing.factors.push(factor);
    else grouped.set(key, { kind, window, factors: [factor] });
  }
  return [...grouped.entries()].map(([key, group]) => {
    const directions = new Set(group.factors.map((factor) => factor.direction));
    const direction: Tier1DisplayDirection = directions.size === 1 ? group.factors[0].direction : 'MIXED';
    const weatherWindow = group.window !== 'NONE' ? ` trong ${windowDescription(group.window, context.anchorDate)}` : '';
    return {
      key, kind: group.kind, title: `${familyTitles[group.kind]}${weatherWindow}`, direction,
      details: direction === 'MIXED' ? [] : group.factors.map((factor) => formatTier1Factor(factor, context)),
      mixedDetails: direction === 'MIXED' ? group.factors.map((factor) => ({ direction: factor.direction, label: formatTier1Factor(factor, context) })) : [],
      // Keep each original value/direction; no group SHAP arithmetic or net effect.
      rawFactors: group.factors,
    };
  });
}
