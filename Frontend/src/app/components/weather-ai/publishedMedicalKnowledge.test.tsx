import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type {
  PublishedMedicalKnowledgeItem,
  WeatherAIDiseaseRanking,
  WeatherAIPredictResponse,
  WeatherAITier1Factor,
} from '@/lib/api';
import { PublishedMedicalKnowledgeSections } from './WeatherAIResults';
import { buildPublishedMedicalKnowledgeSelectors } from './publishedMedicalKnowledge';

function factor(
  weatherFactor: string | null,
  overrides: Partial<WeatherAITier1Factor> = {},
): WeatherAITier1Factor {
  return {
    feature: `feature_${weatherFactor}`,
    label_vi: 'Nhãn chỉ dùng để hiển thị',
    category: 'WEATHER',
    window: '7D',
    input_value: 1,
    shap_value: 0.5,
    direction: 'UP',
    weather_factor: weatherFactor,
    ...overrides,
  };
}

function prediction(
  diseaseGroupId: string,
  positiveFactors: WeatherAITier1Factor[],
): WeatherAIDiseaseRanking {
  return {
    rank: 1,
    disease_id: diseaseGroupId,
    disease_name: `Nhóm ${diseaseGroupId}`,
    disease_group_id: diseaseGroupId,
    disease_group_name: `Nhóm ${diseaseGroupId}`,
    report_group_code: 'R1',
    ranking_score: 0.8,
    tier1: {
      available: true,
      positive_factors: positiveFactors,
      negative_factors: [],
    },
    tier2: { available: false, sources: [] },
  };
}

function response(predictions: WeatherAIDiseaseRanking[]): WeatherAIPredictResponse {
  return {
    message: 'ok',
    context: {
      age_group: '1-5 tuổi',
      gender: 'Nam',
      anchor_date: '2026-08-23',
      horizon: '14D',
      top_k: predictions.length,
      ranking_universe: 221,
    },
    input: { age_group: '1-5 tuổi', gender: 'Nam', top_k: predictions.length },
    weather: { features: {} },
    predictions,
    top_risks: predictions,
    model: {
      model_type: 'LightGBM',
      horizon: '14D',
      with_weather: true,
      model_count: 221,
      score_semantics: 'ranking',
    },
    runtime_ms: {},
    disclaimer: 'Không thay thế chẩn đoán.',
  };
}

const item: PublishedMedicalKnowledgeItem = {
  disease_group_id: '17',
  factor_type: 'WEATHER',
  factor_key: 'precipitation',
  factor_value: null,
  weather_factor: 'precipitation',
  revision_id: 9,
  knowledge_type: 'REVIEWED',
  warning: null,
  evidence_level: 'SUPPORTED',
  evidence_scope: 'PARTIAL_GROUP',
  short_explanation_vi: 'Giải thích ngắn đã được duyệt.',
  detailed_explanation_vi: 'Giải thích chi tiết chỉ dựa trên bằng chứng đã chọn.',
  limitations_vi: 'Bằng chứng quan sát không chứng minh quan hệ nhân quả.',
  sources: [{
    title: 'Published evidence title',
    journal: 'Medical Journal',
    publication_year: 2025,
    pmid: '12345678',
    doi: '10.1000/example',
    pmcid: null,
    url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
  }],
};

describe('published Medical Knowledge selector mapping', () => {
  it('uses canonical Tier-1 identifiers, positive ordering, and deterministic deduplication', () => {
    const selectors = buildPublishedMedicalKnowledgeSelectors(response([
      prediction('17', [
        factor('precipitation'),
        factor('humidity'),
        factor('precipitation'),
        factor('wind', { direction: 'DOWN', shap_value: -0.4 }),
        factor('temperature', { category: 'DEMOGRAPHIC' }),
        factor('RAIN'),
      ]),
      prediction('22', [factor('weather_code'), factor('temperature')]),
    ]));

    expect(selectors).toEqual([
      { disease_group_id: '17', factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null, weather_factor: 'precipitation' },
      { disease_group_id: '17', factor_type: 'WEATHER', factor_key: 'humidity', factor_value: null, weather_factor: 'humidity' },
      { disease_group_id: '22', factor_type: 'WEATHER', factor_key: 'weather_condition', factor_value: null, weather_factor: 'weather_condition' },
      { disease_group_id: '22', factor_type: 'WEATHER', factor_key: 'temperature', factor_value: null, weather_factor: 'temperature' },
    ]);
  });

  it('does not infer a selector from display text or a negative factor', () => {
    expect(buildPublishedMedicalKnowledgeSelectors(response([
      prediction('17', [
        factor(null, { feature: 'custom', label_vi: 'Mưa rất nhiều' }),
        factor('humidity', { direction: 'DOWN', shap_value: -2 }),
      ]),
    ]))).toEqual([]);
  });

  it('maps age, sex, and seasonality only from positive canonical Tier-1 fields', () => {
    const selectors = buildPublishedMedicalKnowledgeSelectors(response([
      prediction('17', [
        factor(null, { category: 'DEMOGRAPHIC', feature: 'age_group', input_value: '1-5 tuổi' }),
        factor(null, { category: 'DEMOGRAPHIC', feature: 'gender', input_value: 'Nam' }),
        factor(null, { category: 'SEASONAL_CALENDAR', feature: 'month', input_value: 8 }),
        factor(null, { category: 'SEASONAL_CALENDAR', feature: 'season', input_value: 'Mùa mưa' }),
      ]),
    ]));
    expect(selectors).toEqual([
      { disease_group_id: '17', factor_type: 'AGE', factor_key: 'age_group', factor_value: '1-5 tuổi', weather_factor: null },
      { disease_group_id: '17', factor_type: 'SEX', factor_key: 'gender', factor_value: 'Nam', weather_factor: null },
      { disease_group_id: '17', factor_type: 'SEASONALITY', factor_key: 'time_of_year', factor_value: null, weather_factor: null },
    ]);
  });
});

describe('published Medical Knowledge parent presentation', () => {
  it.each([
    ['AGE', 'age_group', '1-5 tuổi', 'Độ tuổi — 1-5 tuổi'],
    ['SEX', 'gender', 'Nam', 'Giới tính — Nam'],
    ['SEASONALITY', 'time_of_year', null, 'Tính mùa vụ'],
  ] as const)('labels %s Tier-2 content under the matching Tier-1 factor', (factorType, factorKey, factorValue, expected) => {
    render(<PublishedMedicalKnowledgeSections items={[{
      ...item,
      factor_type: factorType,
      factor_key: factorKey,
      factor_value: factorValue,
      weather_factor: null,
    }]} />);
    expect(screen.getByText(new RegExp(expected))).toBeVisible();
  });

  it('renders reviewed short content, expandable details, limitations, and bibliography', () => {
    render(<PublishedMedicalKnowledgeSections items={[item]} />);

    expect(screen.getByRole('region', { name: 'Giải thích y khoa' })).toBeInTheDocument();
    expect(screen.getByText(item.short_explanation_vi)).toBeVisible();
    expect(screen.getByText('Có cơ sở y khoa tương đối rõ')).toBeVisible();
    expect(screen.getByText(/Bằng chứng quan sát không chứng minh/)).toBeVisible();
    expect(screen.getByText(/Published evidence title/)).toHaveTextContent('PMID 12345678');
    const details = screen.getByText('Xem giải thích chi tiết').parentElement as HTMLDetailsElement;
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText('Xem giải thích chi tiết'));
    expect(details.open).toBe(true);
    expect(screen.getByText(item.detailed_explanation_vi)).toBeInTheDocument();
  });

  it('uses safe citation links and never renders internal/admin fields', () => {
    const unsafe = {
      ...item,
      sources: [{ ...item.sources[0], url: 'javascript:alert(1)' }],
    };
    const { container } = render(<PublishedMedicalKnowledgeSections items={[unsafe]} />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent(/source_assessment|PRIMARY|DIRECT|provider|prompt|reviewer/i);
    expect(container).not.toHaveTextContent('javascript:alert(1)');
  });

  it('distinguishes Auto fallback with the required unreviewed warning', () => {
    const warning = 'Giải thích tự động bởi AI — chưa được nhân viên y tế kiểm duyệt.';
    render(<PublishedMedicalKnowledgeSections items={[{
      ...item,
      knowledge_type: 'AUTO',
      generation_mode: 'SAFE_FALLBACK',
      warning,
    }]} />);
    expect(screen.getByText(/nội dung được tạo tự động/i)).toBeVisible();
    expect(screen.getByText(warning)).toBeVisible();
    expect(screen.getByText('Giải thích tự động rút gọn')).toBeVisible();
    expect(screen.queryByText(/Đã được kiểm duyệt/)).not.toBeInTheDocument();
  });

  it('is absent for an empty result and has a section-only loading state', () => {
    const { rerender } = render(<PublishedMedicalKnowledgeSections items={[]} />);
    expect(screen.queryByRole('region', { name: 'Giải thích y khoa' })).not.toBeInTheDocument();
    rerender(<PublishedMedicalKnowledgeSections items={[]} loading />);
    expect(screen.getByRole('status')).toHaveTextContent('Đang tải giải thích y khoa bổ sung');
  });

  it('renders only the replacement revision supplied by the publication pointer', () => {
    render(<PublishedMedicalKnowledgeSections items={[{
      ...item,
      revision_id: 10,
      short_explanation_vi: 'Nội dung revision mới.',
    }]} />);
    expect(screen.getByText('Nội dung revision mới.')).toBeVisible();
    expect(screen.queryByText(item.short_explanation_vi)).not.toBeInTheDocument();
  });
});
