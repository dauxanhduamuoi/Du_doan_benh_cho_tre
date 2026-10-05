import type { WeatherAIFactorWindow } from '@/lib/api';

export type Tier1FeatureFamily =
  | 'AGE' | 'GENDER' | 'TIME_OF_YEAR' | 'TEMPERATURE' | 'HUMIDITY'
  | 'PRECIPITATION' | 'WIND' | 'WEATHER_CONDITION';

export interface Tier1FeatureDefinition {
  feature: string;
  family: Tier1FeatureFamily;
  statistic: 'CATEGORY' | 'MONTH' | 'SIN' | 'COS' | 'MEAN' | 'MIN' | 'MAX'
    | 'SUM' | 'MAX_DAILY' | 'RAIN_DAYS' | 'RAIN_DAY' | 'MODE';
  unit: '' | '°C' | '%' | 'mm' | 'km/h' | 'ngày';
  window: WeatherAIFactorWindow;
  descriptionVi: string;
}

// Presentation metadata only: the deployed schema has coarse human labels but
// no statistic/units. Exact keys follow weather_ai_features.py; never model order.
const definitions: Record<string, Tier1FeatureDefinition> = Object.create(null);
function define(
  feature: string, family: Tier1FeatureFamily,
  statistic: Tier1FeatureDefinition['statistic'], unit: Tier1FeatureDefinition['unit'],
  window: WeatherAIFactorWindow, descriptionVi: string,
) {
  definitions[feature] = Object.freeze({ feature, family, statistic, unit, window, descriptionVi });
}

define('age_group', 'AGE', 'CATEGORY', '', 'NONE', 'Nhóm tuổi');
define('gender', 'GENDER', 'CATEGORY', '', 'NONE', 'Giới tính');
define('month', 'TIME_OF_YEAR', 'MONTH', '', 'NONE', 'Tháng của ngày dữ liệu');
define('season', 'TIME_OF_YEAR', 'CATEGORY', '', 'NONE', 'Mùa theo quy ước của mô hình');
define('day_of_year_sin', 'TIME_OF_YEAR', 'SIN', '', 'NONE', 'Đặc trưng chu kỳ thời điểm trong năm (sin)');
define('day_of_year_cos', 'TIME_OF_YEAR', 'COS', '', 'NONE', 'Đặc trưng chu kỳ thời điểm trong năm (cos)');
define('weather_code_current', 'WEATHER_CONDITION', 'MODE', '', 'CURRENT', 'Mã trạng thái thời tiết phổ biến nhất');
define('rain_day_current', 'PRECIPITATION', 'RAIN_DAY', '', 'CURRENT', 'Chỉ báo lượng mưa lớn hơn 0');

type WeatherDefinition = readonly [string, Tier1FeatureFamily, Tier1FeatureDefinition['statistic'], Tier1FeatureDefinition['unit'], string];
const weatherDefinitions: WeatherDefinition[] = [
  ['temperature_mean', 'TEMPERATURE', 'MEAN', '°C', 'Nhiệt độ trung bình'],
  ['temperature_min', 'TEMPERATURE', 'MIN', '°C', 'Nhiệt độ thấp nhất'],
  ['temperature_max', 'TEMPERATURE', 'MAX', '°C', 'Nhiệt độ cao nhất'],
  ['humidity_mean', 'HUMIDITY', 'MEAN', '%', 'Độ ẩm trung bình'],
  ['humidity_min', 'HUMIDITY', 'MIN', '%', 'Độ ẩm thấp nhất'],
  ['humidity_max', 'HUMIDITY', 'MAX', '%', 'Độ ẩm cao nhất'],
  ['wind_speed_mean', 'WIND', 'MEAN', 'km/h', 'Tốc độ gió trung bình'],
  ['wind_speed_max', 'WIND', 'MAX', 'km/h', 'Tốc độ gió lớn nhất'],
  ['wind_gust_max', 'WIND', 'MAX', 'km/h', 'Tốc độ gió giật lớn nhất'],
  ['precipitation_sum', 'PRECIPITATION', 'SUM', 'mm', 'Tổng lượng giáng thủy'],
  ['rain_sum', 'PRECIPITATION', 'SUM', 'mm', 'Tổng lượng mưa'],
];
const windows: ReadonlyArray<readonly [string, WeatherAIFactorWindow]> = [
  ['current', 'CURRENT'], ['3d', '3D'], ['7d', '7D'],
];
for (const [suffix, window] of windows) {
  for (const [base, family, statistic, unit, description] of weatherDefinitions) {
    define(`${base}_${suffix}`, family, statistic, unit, window, description);
  }
  if (window !== 'CURRENT') {
    define(`rain_days_${suffix}`, 'PRECIPITATION', 'RAIN_DAYS', 'ngày', window, 'Số ngày có lượng mưa lớn hơn 0');
    define(`rain_max_daily_${suffix}`, 'PRECIPITATION', 'MAX_DAILY', 'mm', window, 'Lượng mưa trong ngày lớn nhất');
  }
}

export const TIER1_FEATURE_DEFINITIONS: Readonly<Record<string, Readonly<Tier1FeatureDefinition>>> = Object.freeze(definitions);
