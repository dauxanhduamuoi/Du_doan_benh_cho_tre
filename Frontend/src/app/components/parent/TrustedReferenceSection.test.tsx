import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TrustedReferenceItem, TrustedReferenceSelector, WeatherAIPredictResponse, WeatherAITier1Factor } from '@/lib/api';
import { buildTrustedReferenceSelectors, matchTrustedReferenceItems } from '../weather-ai/trustedReferences';
import { TrustedReferenceSection } from './TrustedReferenceSection';

const selector: TrustedReferenceSelector = {
  disease_group_id: '17', factor_type: 'WEATHER', factor_key: 'humidity', factor_value: null,
};
const reference = {
  source_id: 5, provider_id: 'WHO', external_id: 'stored', source_type: 'WHO', source_kind: 'HEALTH_GUIDANCE',
  title: 'Nguồn đã lưu', journal: 'Tạp chí đã lưu', publication_year: 2025, original_url: 'https://example.org/source',
};
function factor(overrides: Partial<WeatherAITier1Factor> = {}): WeatherAITier1Factor {
  return { feature: 'humidity_mean_7d', category: 'WEATHER', weather_factor: 'humidity', window: '7D',
    label_vi: 'Không dùng nhãn này để đoán selector', input_value: 83, shap_value: 0.8, direction: 'UP', ...overrides };
}
function prediction(factors: WeatherAITier1Factor[]): WeatherAIPredictResponse {
  return {
    message: 'ok', context: { age_group: '1-5 tuổi', gender: 'Nam', anchor_date: '2026-10-06', horizon: '14D', top_k: 5, ranking_universe: 221 },
    input: { age_group: '1-5 tuổi', gender: 'Nam', top_k: 5 }, weather: { features: {} }, top_risks: [],
    predictions: [{ rank: 1, disease_id: '17', disease_group_id: '17', disease_name: 'Bệnh', disease_group_name: 'Bệnh', ranking_score: 0.9,
      tier1: { available: true, positive_factors: factors, negative_factors: [factor({ weather_factor: 'wind', direction: 'DOWN', shap_value: -1 })] },
      tier2: { available: false, sources: [] } }],
    model: { model_type: 'LightGBM', horizon: '14D', with_weather: true, model_count: 221, score_semantics: 'ranking' }, runtime_ms: {}, disclaimer: '',
  };
}

describe('Trusted References selectors', () => {
  it('reuses all canonical factor families from positive Tier-1 factors only', () => {
    const result = buildTrustedReferenceSelectors(prediction([
      factor({ category: 'DEMOGRAPHIC', feature: 'age_group', input_value: '1-5 tuổi', weather_factor: null }),
      factor({ category: 'DEMOGRAPHIC', feature: 'gender', input_value: 'Nam', weather_factor: null }),
      factor({ category: 'SEASONAL_CALENDAR', feature: 'month', input_value: 10, weather_factor: null }),
      factor({ category: 'SEASONAL_CALENDAR', feature: 'season', input_value: 'Mùa mưa', weather_factor: null }),
      ...['temperature', 'humidity', 'precipitation', 'wind', 'weather_code'].map((weather_factor) => factor({ weather_factor })),
      factor({ window: 'CURRENT' }), factor({ window: '3D' }),
      factor({ weather_factor: 'temperature', direction: 'DOWN', shap_value: -2 }),
      factor({ shap_value: 0 }), factor({ weather_factor: 'unknown' }),
    ]));
    expect(result).toEqual([
      { ...selector, factor_type: 'AGE', factor_key: 'age_group', factor_value: '1-5 tuổi' },
      { ...selector, factor_type: 'SEX', factor_key: 'gender', factor_value: 'Nam' },
      { ...selector, factor_type: 'SEASONALITY', factor_key: 'time_of_year' },
      ...['temperature', 'humidity', 'precipitation', 'wind', 'weather_condition'].map((factor_key) => ({ ...selector, factor_key })),
    ]);
    result.forEach((item) => expect(Object.keys(item).sort()).toEqual(['disease_group_id', 'factor_key', 'factor_type', 'factor_value']));
  });

  it.each([
    [{ ...selector, factor_type: 'AGE', factor_key: 'age_group', factor_value: '1-5 tuổi' }, { ...selector, factor_type: 'AGE', factor_key: 'age_group', factor_value: '6-10 tuổi' }],
    [{ ...selector, factor_type: 'SEX', factor_key: 'gender', factor_value: 'Nam' }, { ...selector, factor_type: 'SEX', factor_key: 'gender', factor_value: 'Nữ' }],
    [selector, { ...selector, factor_value: '83' }],
    [selector, { ...selector, factor_key: 'temperature' }],
    [selector, { ...selector, disease_group_id: '18' }],
    [{ ...selector, factor_type: 'SEASONALITY', factor_key: 'time_of_year' }, selector],
  ] as [TrustedReferenceSelector, TrustedReferenceSelector][])('matches all four selector components: %j', (requested, wrong) => {
    const items = [{ selector: wrong, references: [reference] }, { selector: requested, references: [reference] }];
    expect(matchTrustedReferenceItems(items, [requested])).toEqual([items[1]]);
  });
});

describe('Trusted Reference metadata cards', () => {
  it('starts collapsed when requested and exposes the same safe sources after expansion', () => {
    render(<TrustedReferenceSection items={[{ selector, references: [reference] }]} collapsible />);
    const summary = screen.getByText('Xem tài liệu tham khảo (1)');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(reference.title)).not.toBeVisible();
    expect(screen.getByRole('link')).not.toBeVisible();
    fireEvent.click(summary);
    expect(summary.closest('details')).toHaveAttribute('open');
    expect(screen.getByRole('link', { name: `Xem nguồn gốc: ${reference.title}` })).toHaveAttribute('href', reference.original_url);
    fireEvent.click(summary);
    expect(screen.getByText(reference.title)).not.toBeVisible();
  });

  it('renders metadata, a safe original link and neutral reference wording', () => {
    render(<TrustedReferenceSection items={[{ selector, references: [reference] }]} />);
    expect(screen.getByRole('region', { name: 'Nguồn tham khảo' })).toBeVisible();
    expect(screen.getByText(reference.title)).toBeVisible();
    expect(screen.getByText('Tạp chí đã lưu · 2025 · WHO')).toBeVisible();
    expect(screen.getByText(/dùng để đọc thêm và không quyết định kết quả xếp hạng/)).toBeVisible();
    expect(screen.getByRole('link', { name: `Xem nguồn gốc: ${reference.title}` })).toHaveAttribute('href', reference.original_url);
    expect(screen.getByRole('link')).toHaveAttribute('target', '_blank');
    expect(screen.getByRole('link')).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('preserves API source order and dedups by persisted source identity', () => {
    render(<TrustedReferenceSection items={[{ selector, references: [reference, { ...reference, source_id: 2, title: 'Nguồn thứ hai' }, reference] }]} />);
    expect(screen.getAllByRole('heading', { level: 5 }).map((node) => node.textContent)).toEqual(['Nguồn đã lưu', 'Nguồn thứ hai']);
    expect(screen.getByRole('link', { name: 'Xem nguồn gốc: Nguồn đã lưu' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Xem nguồn gốc: Nguồn thứ hai' })).toBeVisible();
  });

  it('wraps long bibliography tokens without truncating content', () => {
    const title = 'TiêuĐềDài'.repeat(50);
    const journal = 'TênTạpChíDài'.repeat(40);
    render(<TrustedReferenceSection items={[{ selector, references: [{ ...reference, title, journal }] }]} />);
    expect(screen.getByRole('heading', { name: title })).toHaveClass('[overflow-wrap:anywhere]');
    expect(screen.getByText(`${journal} · 2025 · WHO`)).toHaveClass('[overflow-wrap:anywhere]');
    expect(screen.getByRole('link', { name: `Xem nguồn gốc: ${title}` })).toHaveAttribute('href', reference.original_url);
  });

  it.each([{ items: [] }, { items: [{ selector, references: [] }] }] as { items: TrustedReferenceItem[] }[])('hides an empty reference section', ({ items }) => {
    const { container } = render(<TrustedReferenceSection items={items} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(['javascript:alert(1)', 'http://example.org/source', '/relative', 'https://', 'https:example.org', 'https://example.org/bad path', 'https://user:password@example.org/source'])('does not link an unsafe URL: %s', (original_url) => {
    render(<TrustedReferenceSection items={[{ selector, references: [{ ...reference, original_url }] }]} />);
    expect(screen.getByText(reference.title)).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByText(original_url)).not.toBeInTheDocument();
  });

  it('renders neither generated prose nor internal fields even if extra fields arrive', () => {
    const polluted = { ...reference, short_explanation_vi: 'PRIVATE SHORT', detailed_explanation_vi: 'PRIVATE DETAIL', limitations_vi: 'PRIVATE LIMIT', llm_model: 'PRIVATE MODEL', prompt_version: 'PRIVATE PROMPT', warning: 'AUTO WARNING' };
    const { container } = render(<TrustedReferenceSection items={[{ selector, references: [polluted] }]} />);
    expect(container).not.toHaveTextContent(/PRIVATE|AUTO WARNING/);
  });
});
