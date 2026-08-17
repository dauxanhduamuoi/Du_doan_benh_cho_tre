import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ApiError,
  weatherAIErrorMessage,
  type WeatherAIDiseaseRanking,
  type WeatherAITier1Factor,
} from '@/lib/api';
import {
  WeatherAILoadingNotice,
  WeatherAIPredictionList,
  evidenceStatusLabel,
  isSafeSourceUrl,
} from './WeatherAIResults';
import { buildTier1DisplayGroups } from './tier1Presentation';

function makePrediction(
  rank: number,
  overrides: Partial<WeatherAIDiseaseRanking> = {},
): WeatherAIDiseaseRanking {
  return {
    rank,
    disease_id: `D${rank}`,
    disease_name: `Nhóm bệnh ${rank}`,
    disease_group_id: `D${rank}`,
    disease_group_name: `Nhóm bệnh ${rank}`,
    report_group_code: `R${rank}`,
    ranking_score: 0.91 - rank / 100,
    tier1: {
      available: true,
      summary_vi: 'Các yếu tố trong bối cảnh hiện tại ảnh hưởng đến thứ hạng của mô hình.',
      positive_factors: [
        {
          feature: 'rain_sum_7d',
          label_vi: 'Lượng mưa trong 7 ngày gần đây',
          category: 'WEATHER',
          window: '7D',
          input_value: 42,
          shap_value: 0.8,
          direction: 'UP',
          weather_factor: 'RAIN',
        },
      ],
      negative_factors: [
        {
          feature: 'temperature_mean',
          label_vi: 'Nhiệt độ trung bình hiện tại',
          category: 'WEATHER',
          window: 'CURRENT',
          input_value: 30,
          shap_value: -0.2,
          direction: 'DOWN',
          weather_factor: 'TEMPERATURE',
        },
      ],
      base_value_raw: 0,
      additivity_max_abs_error: 0,
      error: null,
    },
    tier2: {
      available: true,
      reason: null,
      evidence_status: 'SUPPORTED',
      relationship_type: 'ASSOCIATION',
      matched_weather_factor: 'RAIN',
      explanation_short_vi: 'Mưa có thể liên quan đến thay đổi phơi nhiễm ở cấp quần thể.',
      limitations_vi: 'Mối liên hệ thống kê không đồng nghĩa thời tiết chắc chắn gây bệnh.',
      sources: [
        {
          title: 'Tổng quan dịch tễ học',
          organization: 'Tổ chức y tế',
          url: 'https://example.org/evidence',
          year: 2024,
        },
      ],
    },
    ...overrides,
  };
}

function makeFactor(
  feature: string,
  direction: 'UP' | 'DOWN',
  overrides: Partial<WeatherAITier1Factor> = {},
): WeatherAITier1Factor {
  return {
    feature,
    label_vi: feature,
    category: 'WEATHER',
    window: '7D',
    input_value: null,
    shap_value: direction === 'UP' ? 0.5 : -0.5,
    direction,
    weather_factor: null,
    ...overrides,
  };
}

function withTier1Factors(
  positive_factors: WeatherAITier1Factor[],
  negative_factors: WeatherAITier1Factor[] = [],
): WeatherAIDiseaseRanking {
  const prediction = makePrediction(2);
  return {
    ...prediction,
    tier1: {
      ...prediction.tier1,
      positive_factors,
      negative_factors,
    },
  };
}

describe('Weather AI V3 result rendering', () => {
  it('renders a Top-5 ranking in backend rank order', () => {
    render(<WeatherAIPredictionList predictions={[1, 2, 3, 4, 5].map((rank) => makePrediction(rank))} />);
    expect(screen.getAllByTestId('weather-ai-prediction-card')).toHaveLength(5);
    expect(screen.getByLabelText('Xếp hạng 1')).toHaveTextContent('#1');
    expect(screen.getByLabelText('Xếp hạng 5')).toHaveTextContent('#5');
  });

  it('does not render ranking score as a percentage or probability', () => {
    const { container } = render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    expect(container.textContent).not.toContain('%');
    expect(container.textContent).not.toMatch(/xác suất|phần trăm/i);
    expect(container.textContent).not.toContain('0.9');
  });

  it('renders Tier 1 positive factors with UP text and arrow', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    expect(screen.getByText(/Đang làm nhóm bệnh này được xếp cao hơn/)).toBeInTheDocument();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeInTheDocument();
    expect(screen.getByText('Tổng lượng mưa trong 7 ngày gần đây: 42 mm')).toBeInTheDocument();
  });

  it('renders Tier 1 negative factors with DOWN text and arrow', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    expect(screen.getByText(/Đang làm nhóm bệnh này được xếp thấp hơn/)).toBeInTheDocument();
    expect(screen.getByText('Nhiệt độ hiện tại')).toBeInTheDocument();
    expect(screen.getByText('Nhiệt độ trung bình hiện tại: 30°C')).toBeInTheDocument();
  });

  it('renders the actual age-group input in parent-friendly wording', () => {
    const prediction = withTier1Factors([
      makeFactor('age_group', 'UP', {
        label_vi: 'Nhóm tuổi',
        category: 'DEMOGRAPHIC',
        window: 'NONE',
        input_value: '1-5 tuổi',
      }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getByText('Trẻ thuộc nhóm 1–5 tuổi')).toBeInTheDocument();
    expect(screen.queryByText(/^Nhóm tuổi$/)).not.toBeInTheDocument();
  });

  it('deduplicates day-of-year sin and cos into one time-of-year card', () => {
    const prediction = withTier1Factors([
      makeFactor('day_of_year_sin', 'UP', {
        label_vi: 'Thời điểm trong năm',
        category: 'SEASONAL_CALENDAR',
        window: 'NONE',
        input_value: 0.4,
      }),
      makeFactor('day_of_year_cos', 'UP', {
        label_vi: 'Thời điểm trong năm',
        category: 'SEASONAL_CALENDAR',
        window: 'NONE',
        input_value: -0.9,
      }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getAllByText('Thời điểm trong năm')).toHaveLength(1);
    expect(screen.getAllByTestId('tier1-group-seasonal:time-of-year')).toHaveLength(1);
  });

  it('groups month and season into one actual time-of-year description', () => {
    const prediction = withTier1Factors([
      makeFactor('month', 'UP', {
        label_vi: 'Yếu tố mùa vụ theo tháng',
        category: 'SEASONAL_CALENDAR',
        window: 'NONE',
        input_value: 8,
      }),
      makeFactor('season', 'UP', {
        label_vi: 'Mùa mưa / mùa khô',
        category: 'SEASONAL_CALENDAR',
        window: 'NONE',
        input_value: 'Mùa mưa',
      }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getAllByText('Thời điểm trong năm')).toHaveLength(1);
    expect(screen.getByText('Hiện tại là tháng 8, thuộc mùa mưa.')).toBeInTheDocument();
  });

  it('groups temperature min, mean and max in the same window into one card', () => {
    const prediction = withTier1Factors([
      makeFactor('temperature_min_7d', 'UP', { input_value: 26 }),
      makeFactor('temperature_mean_7d', 'UP', { input_value: 29 }),
      makeFactor('temperature_max_7d', 'UP', { input_value: 33 }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getAllByTestId('tier1-group-weather:TEMPERATURE:7D')).toHaveLength(1);
    expect(screen.getAllByText('Nhiệt độ trong 7 ngày gần đây')).toHaveLength(1);
  });

  it('formats an actual temperature min/max range without inventing values', () => {
    const prediction = withTier1Factors([
      makeFactor('temperature_min_7d', 'UP', { input_value: 26 }),
      makeFactor('temperature_max_7d', 'UP', { input_value: 33 }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getByText('Nhiệt độ trong 7 ngày gần đây: 26–33°C')).toBeInTheDocument();
  });

  it('uses a human-readable fallback when input_value is missing', () => {
    const prediction = withTier1Factors([
      makeFactor('humidity_mean_7d', 'UP', {
        label_vi: 'Độ ẩm — 7 ngày gần đây',
        input_value: undefined,
      }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    const group = screen.getByTestId('tier1-group-weather:HUMIDITY:7D');
    expect(group).toHaveTextContent('Độ ẩm trong 7 ngày gần đây');
    expect(group).toHaveTextContent('Điều kiện này đang được AI sử dụng để xếp hạng.');
    expect(group.textContent).not.toMatch(/\d+\s*%/);
  });

  it('places positive SHAP factors only in the higher-ranking section', () => {
    const prediction = withTier1Factors([
      makeFactor('rain_sum_7d', 'UP', { input_value: 12 }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    const higher = screen.getByText(/Đang làm nhóm bệnh này được xếp cao hơn/).parentElement;
    expect(higher).not.toBeNull();
    expect(within(higher as HTMLElement).getByText('Mưa trong 7 ngày gần đây')).toBeInTheDocument();
    expect(screen.queryByText(/Đang làm nhóm bệnh này được xếp thấp hơn/)).not.toBeInTheDocument();
  });

  it('places negative SHAP factors only in the lower-ranking section', () => {
    const prediction = withTier1Factors([], [
      makeFactor('wind_speed_mean_7d', 'DOWN', { input_value: 15 }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    const lower = screen.getByText(/Đang làm nhóm bệnh này được xếp thấp hơn/).parentElement;
    expect(lower).not.toBeNull();
    expect(within(lower as HTMLElement).getByText('Gió trong 7 ngày gần đây')).toBeInTheDocument();
    expect(screen.queryByText(/Đang làm nhóm bệnh này được xếp cao hơn/)).not.toBeInTheDocument();
  });

  it('keeps a mixed-direction family neutral instead of making a false UP or DOWN claim', () => {
    const prediction = withTier1Factors(
      [makeFactor('temperature_min_7d', 'UP', { input_value: 26 })],
      [makeFactor('temperature_max_7d', 'DOWN', { input_value: 33 })],
    );
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    const mixed = screen.getByText(/Các yếu tố có tác động theo nhiều chiều/).parentElement;
    expect(mixed).not.toBeNull();
    expect(within(mixed as HTMLElement).getByText('Nhiệt độ trong 7 ngày gần đây')).toBeInTheDocument();
    expect(mixed).toHaveTextContent('theo các hướng khác nhau');
    expect(screen.queryByText(/Đang làm nhóm bệnh này được xếp cao hơn/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Đang làm nhóm bệnh này được xếp thấp hơn/)).not.toBeInTheDocument();
  });

  it('does not render raw SHAP values', () => {
    const prediction = withTier1Factors([
      makeFactor('rain_sum_7d', 'UP', { input_value: 12, shap_value: 123.456789 }),
    ]);
    const { container } = render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(container).not.toHaveTextContent('123.456789');
  });

  it('does not render raw technical feature names when a human presentation exists', () => {
    const prediction = withTier1Factors([
      makeFactor('humidity_mean_7d', 'UP', { input_value: 84 }),
    ]);
    const { container } = render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(container).toHaveTextContent('Độ ẩm trong 7 ngày gần đây');
    expect(container).not.toHaveTextContent('humidity_mean_7d');
  });

  it('builds a separate presentation model without mutating raw factors', () => {
    const positive = [makeFactor('temperature_mean_7d', 'UP', { input_value: 29 })];
    const negative = [makeFactor('wind_speed_mean_7d', 'DOWN', { input_value: 15 })];
    const before = JSON.parse(JSON.stringify({ positive, negative }));
    const groups = buildTier1DisplayGroups(positive, negative);
    expect(groups).toHaveLength(2);
    expect({ positive, negative }).toEqual(before);
  });

  it('uses non-causal wording inside the Tier 1 explanation', () => {
    const prediction = withTier1Factors([
      makeFactor('humidity_mean_7d', 'UP', { input_value: 84 }),
    ]);
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    const tier1Section = screen.getByLabelText('Giải thích xếp hạng của mô hình');
    expect(tier1Section).not.toHaveTextContent(/nguyên nhân gây|làm trẻ mắc|độ ẩm cao làm nguy cơ tăng/i);
    expect(tier1Section).toHaveTextContent(/không có nghĩa các yếu tố này trực tiếp gây ra bệnh/i);
  });

  it('renders available Tier 2 explanation and limitations', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    expect(screen.getByText(/Mưa có thể liên quan/)).toBeInTheDocument();
    expect(screen.getByText(/không đồng nghĩa thời tiết chắc chắn gây bệnh/)).toBeInTheDocument();
  });

  it('keeps the disease card normal when Tier 2 is unavailable', () => {
    const prediction = makePrediction(1, {
      tier2: {
        available: false,
        reason: 'NO_MEDICAL_KNOWLEDGE',
        evidence_status: null,
        relationship_type: null,
        matched_weather_factor: null,
        explanation_short_vi: null,
        limitations_vi: null,
        sources: [],
      },
    });
    render(<WeatherAIPredictionList predictions={[prediction]} />);
    expect(screen.getByText('Nhóm bệnh 1')).toBeInTheDocument();
    expect(screen.queryByText(/NO_MEDICAL_KNOWLEDGE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Vì sao yếu tố thời tiết này/)).not.toBeInTheDocument();
  });

  it('uses cautious Vietnamese wording for SUPPORTED evidence', () => {
    expect(evidenceStatusLabel('SUPPORTED')).toBe('Có cơ sở y khoa tương đối rõ');
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    expect(screen.getByText('Có cơ sở y khoa tương đối rõ')).toBeInTheDocument();
  });

  it('uses cautious Vietnamese wording for LIMITED_OR_INDIRECT evidence', () => {
    expect(evidenceStatusLabel('LIMITED_OR_INDIRECT')).toBe('Bằng chứng còn hạn chế / gián tiếp');
  });

  it('renders a safe source link with secure new-tab attributes', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} />);
    const link = screen.getByRole('link', { name: /Mở nguồn tham khảo/ });
    expect(link).toHaveAttribute('href', 'https://example.org/evidence');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('does not create links for unsafe source URLs', () => {
    expect(isSafeSourceUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeSourceUrl('http://example.org')).toBe(false);
  });

  it('always renders the backend disclaimer', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} disclaimer="Disclaimer từ backend." />);
    expect(screen.getByText('Disclaimer từ backend.')).toBeVisible();
  });

  it('renders a safe fallback disclaimer when the backend text is empty', () => {
    render(<WeatherAIPredictionList predictions={[makePrediction(1)]} disclaimer="" />);
    expect(screen.getByText(/không thay thế chẩn đoán của bác sĩ/i)).toBeVisible();
  });

  it('renders an accessible loading status', () => {
    render(<WeatherAILoadingNotice />);
    expect(screen.getByRole('status')).toHaveTextContent(/Đang lấy thời tiết/);
  });
});

describe('Weather AI API errors', () => {
  it.each([
    [422, 'Thông tin đầu vào chưa hợp lệ.'],
    [503, 'Hệ thống dự đoán tạm thời chưa sẵn sàng.'],
    [500, 'Đã có lỗi khi xử lý. Vui lòng thử lại.'],
  ])('maps HTTP %s to a parent-friendly message', (status, expected) => {
    expect(weatherAIErrorMessage(new ApiError(status, 'technical detail'))).toBe(expected);
  });
});

describe('Weather AI legacy contract migration', () => {
  it('has no legacy prediction fields in a V3 ranking record', () => {
    const row = makePrediction(1) as unknown as Record<string, unknown>;
    expect(row).not.toHaveProperty('probability');
    expect(row).not.toHaveProperty('predicted_cases');
    expect(row).not.toHaveProperty('risk_score');
    expect(row).not.toHaveProperty('risk_level');
  });
});
