import { describe, expect, it } from 'vitest';
import type { WeatherAITier1Factor } from '@/lib/api';
import schema from '../../../../../weather_disease_ai_v3/deployment/lightgbm_h14_weather/feature_schema.json';
import { TIER1_FEATURE_DEFINITIONS } from './tier1FeatureDefinitions';
import { buildTier1DisplayGroups, formatTier1Factor } from './tier1Presentation';

const context = { diseaseName: 'Viêm phổi', anchorDate: '2026-10-05' };
function factor(feature: string, input_value: unknown, direction: 'UP' | 'DOWN' = 'UP'): WeatherAITier1Factor {
  return { feature, input_value, direction, shap_value: direction === 'UP' ? 0.4 : -0.8,
    label_vi: feature, category: 'WEATHER', window: '7D', weather_factor: null };
}

describe('deterministic Tier 1 presentation', () => {
  it('defines exactly the locked 45 features without modifying the deployment contract', () => {
    expect(Object.keys(TIER1_FEATURE_DEFINITIONS).sort()).toEqual([...schema.feature_order].sort());
    expect(schema.feature_count).toBe(45);
    expect(TIER1_FEATURE_DEFINITIONS.humidity_max_7d).toMatchObject({ family: 'HUMIDITY', statistic: 'MAX', unit: '%', window: '7D' });
    expect(TIER1_FEATURE_DEFINITIONS.wind_speed_mean_3d).toMatchObject({ family: 'WIND', statistic: 'MEAN', unit: 'km/h', window: '3D' });
  });

  it.each([
    ['humidity_mean_7d', 83, 'UP', 'Độ ẩm trung bình trong 7 ngày kết thúc ngày 05/10/2026 là 83%.'],
    ['temperature_min_current', 24, 'DOWN', 'Nhiệt độ thấp nhất trong ngày dữ liệu 05/10/2026 là 24°C.'],
    ['temperature_max_3d', 33.5, 'UP', 'Nhiệt độ cao nhất trong 3 ngày kết thúc ngày 05/10/2026 là 33,5°C.'],
    ['temperature_mean_7d', 29, 'DOWN', 'Nhiệt độ trung bình trong 7 ngày kết thúc ngày 05/10/2026 là 29°C.'],
    ['humidity_max_current', 92, 'UP', 'Độ ẩm cao nhất trong ngày dữ liệu 05/10/2026 là 92%.'],
    ['humidity_min_3d', 61, 'DOWN', 'Độ ẩm thấp nhất trong 3 ngày kết thúc ngày 05/10/2026 là 61%.'],
    ['precipitation_sum_3d', 14.75, 'UP', 'Tổng lượng giáng thủy trong 3 ngày kết thúc ngày 05/10/2026 là 14,75 mm.'],
    ['rain_sum_7d', 42, 'DOWN', 'Tổng lượng mưa trong 7 ngày kết thúc ngày 05/10/2026 là 42 mm.'],
    ['rain_max_daily_7d', 18, 'UP', 'Lượng mưa trong ngày lớn nhất của cửa sổ 7 ngày kết thúc ngày 05/10/2026 là 18 mm.'],
    ['rain_days_3d', 2, 'DOWN', 'Trong cửa sổ 3 ngày kết thúc ngày 05/10/2026, có 2 ngày có lượng mưa lớn hơn 0 theo dữ liệu đầu vào.'],
    ['wind_speed_mean_7d', 12.5, 'UP', 'Tốc độ gió trung bình trong 7 ngày kết thúc ngày 05/10/2026 là 12,5 km/h.'],
    ['wind_speed_max_3d', 24, 'DOWN', 'Tốc độ gió lớn nhất trong 3 ngày kết thúc ngày 05/10/2026 là 24 km/h.'],
    ['wind_gust_max_current', 35, 'UP', 'Tốc độ gió giật lớn nhất trong ngày dữ liệu 05/10/2026 là 35 km/h.'],
    ['age_group', '1-5 tuổi', 'UP', 'Nhóm tuổi được đưa vào mô hình là 1-5 tuổi.'],
    ['gender', 'Nữ', 'DOWN', 'Giới tính được đưa vào mô hình là Nữ.'],
    ['month', 10, 'UP', 'Ngày dữ liệu 05/10/2026 thuộc tháng 10.'],
    ['season', 'Mùa mưa', 'DOWN', 'Theo quy ước mùa được sử dụng trong mô hình, ngày dữ liệu 05/10/2026 thuộc Mùa mưa.'],
    ['day_of_year_sin', -0.123456, 'UP', 'Đặc trưng chu kỳ thời điểm trong năm (sin) của ngày 05/10/2026 có giá trị đầu vào -0,123456.'],
    ['day_of_year_cos', 0.004321, 'DOWN', 'Đặc trưng chu kỳ thời điểm trong năm (cos) của ngày 05/10/2026 có giá trị đầu vào 0,004321.'],
    ['weather_code_current', 95, 'UP', 'Mã trạng thái thời tiết phổ biến nhất trong ngày dữ liệu 05/10/2026 là 95.'],
  ] as const)('formats %s with actual value, window and individual direction', (feature, value, direction, inputSentence) => {
    const text = formatTier1Factor(factor(feature, value, direction), context);
    expect(text).toBe(inputSentence + ` Đặc trưng này đóng góp theo chiều làm ${direction === 'UP' ? 'tăng' : 'giảm'} điểm của nhóm Viêm phổi trong mô hình, so với mức nền của model.`);
    expect(text).not.toMatch(/nguy cơ|xác suất|gây bệnh|gây viêm phổi|tăng \d+ hạng|rất cao|rất thấp|gió mạnh|mưa lớn(?! hơn 0)|ngay lúc này|ngày đã qua/i);
  });

  it('uses the verified binary rain indicator instead of calling the anchor day today', () => {
    const text = formatTier1Factor(factor('rain_day_current', 0), context);
    expect(text).toContain('ngày dữ liệu 05/10/2026 có giá trị đầu vào 0 (1: có; 0: không, theo dữ liệu đầu vào)');
    expect(text).not.toMatch(/hôm nay|hiện tại|mưa lớn(?! hơn 0)/i);
  });

  it('does not decode a weather code or hide its original numeric input', () => {
    const text = formatTier1Factor(factor('weather_code_current', 95), context);
    expect(text).toContain('là 95.');
    expect(text).not.toMatch(/dông|bão|nắng|mây|WMO/i);
  });

  it.each([undefined, null, '', false, {}, NaN, Infinity])('does not invent a numeric weather value for %s', (value) => {
    const text = formatTier1Factor(factor('humidity_mean_7d', value), context);
    expect(text).toContain('chưa có giá trị đầu vào để hiển thị');
    expect(text).not.toMatch(/\d+%|NaN|Infinity/);
    expect(text).toContain('làm tăng điểm');
  });

  it.each([undefined, '2026-02-30', 'invalid', '2026-10-05T00:00:00Z'])('does not invent an anchor date from %s', (anchorDate) => {
    const text = formatTier1Factor(factor('humidity_mean_7d', 83), { ...context, anchorDate });
    expect(text).toContain('7 ngày (chưa cung cấp ngày kết thúc)');
    expect(text).not.toMatch(/hôm nay|gần đây|ngay lúc này/);
  });

  it('uses a valid leap-day anchor without local-timezone date shifts', () => {
    expect(formatTier1Factor(factor('temperature_mean_current', 25), { ...context, anchorDate: '2028-02-29' })).toContain('ngày dữ liệu 29/02/2028 là 25°C');
  });

  it('does not infer metadata for an unknown feature from its prefix or weather_factor', () => {
    const unknown = { ...factor('humidity_invented_7d', 83), label_vi: 'Thông tin bổ sung', weather_factor: 'humidity' };
    const groups = buildTier1DisplayGroups([unknown], [], context);
    expect(groups[0].kind).toBe('OTHER');
    expect(groups[0].details[0]).toContain('Thông tin bổ sung: giá trị đầu vào là 83.');
    expect(groups[0].details[0]).not.toContain('%');
  });

  it('retains each MIXED weather factor and sign without adding or averaging SHAP', () => {
    const positive = Object.freeze(factor('humidity_mean_7d', 83, 'UP'));
    const negative = Object.freeze(factor('humidity_max_7d', 91, 'DOWN'));
    const groups = buildTier1DisplayGroups([positive], [negative], context);
    expect(groups).toHaveLength(1);
    expect(groups[0].direction).toBe('MIXED');
    expect(groups[0].details).toEqual([]);
    expect(groups[0].mixedDetails.map((detail) => detail.direction)).toEqual(['UP', 'DOWN']);
    expect(groups[0].mixedDetails[0].label).toContain('là 83%. Đặc trưng này đóng góp theo chiều làm tăng điểm');
    expect(groups[0].mixedDetails[1].label).toContain('là 91%. Đặc trưng này đóng góp theo chiều làm giảm điểm');
    expect(groups[0].rawFactors[0]).toBe(positive);
    expect(groups[0].rawFactors[1]).toBe(negative);
    expect(groups[0]).not.toHaveProperty('shap_value');
    expect(positive.shap_value).toBe(0.4);
    expect(negative.shap_value).toBe(-0.8);
  });

  it('retains separate sin/cos signs in a MIXED calendar group', () => {
    const groups = buildTier1DisplayGroups([factor('day_of_year_sin', 0.4)], [factor('day_of_year_cos', -0.9, 'DOWN')], context);
    expect(groups[0].direction).toBe('MIXED');
    expect(groups[0].mixedDetails[0].label).toContain('(sin)');
    expect(groups[0].mixedDetails[1].label).toContain('(cos)');
    expect(groups[0].mixedDetails[1].label).toContain('giảm điểm');
  });
});
