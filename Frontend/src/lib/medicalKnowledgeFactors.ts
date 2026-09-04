export type MedicalFactorType = 'WEATHER' | 'AGE' | 'SEX' | 'SEASONALITY';

export interface MedicalFactorSelector {
  factor_type: MedicalFactorType;
  factor_key: string;
  factor_value: string | null;
  weather_factor?: string | null;
}

export interface ExplanationFactorOption {
  type: MedicalFactorType;
  key: string;
  label_vi: string;
  values: string[];
}

export const FACTOR_GROUP_LABELS: Record<MedicalFactorType, string> = {
  AGE: 'Đặc điểm trẻ',
  SEX: 'Đặc điểm trẻ',
  SEASONALITY: 'Thời gian',
  WEATHER: 'Thời tiết',
};

export const WEATHER_FACTOR_LABELS: Record<string, string> = {
  temperature: 'Nhiệt độ',
  humidity: 'Độ ẩm',
  precipitation: 'Mưa / lượng mưa',
  wind: 'Gió',
  weather_condition: 'Điều kiện thời tiết',
};

export function factorOptionId(option: Pick<ExplanationFactorOption, 'type' | 'key'>): string {
  return `${option.type}:${option.key}`;
}

export function factorTopicKey(diseaseGroupId: string, factor: MedicalFactorSelector | null): string {
  return factor
    ? `${diseaseGroupId}\u0000${factor.factor_type}\u0000${factor.factor_key}\u0000${factor.factor_value ?? ''}`
    : `${diseaseGroupId}\u0000`;
}

export function factorLabel(factor: MedicalFactorSelector): string {
  const base = factor.factor_type === 'AGE'
    ? 'Độ tuổi'
    : factor.factor_type === 'SEX'
      ? 'Giới tính'
      : factor.factor_type === 'SEASONALITY'
        ? 'Tính mùa vụ'
        : WEATHER_FACTOR_LABELS[factor.factor_key] ?? 'Yếu tố thời tiết';
  return factor.factor_value ? `${base} — ${factor.factor_value}` : base;
}

export function makeFactorSelector(
  option: ExplanationFactorOption,
  value: string | null = null,
): MedicalFactorSelector {
  return {
    factor_type: option.type,
    factor_key: option.key,
    factor_value: value,
    weather_factor: option.type === 'WEATHER' ? option.key : null,
  };
}

export function factorRequiresValue(factor: MedicalFactorSelector | null): boolean {
  return factor?.factor_type === 'AGE' || factor?.factor_type === 'SEX';
}

export function factorIsComplete(factor: MedicalFactorSelector | null): factor is MedicalFactorSelector {
  return Boolean(factor && (!factorRequiresValue(factor) || factor.factor_value));
}
