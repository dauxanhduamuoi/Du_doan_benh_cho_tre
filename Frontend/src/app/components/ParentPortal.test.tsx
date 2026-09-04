import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  PublishedMedicalKnowledgeItem,
  WeatherAIDiseaseRanking,
  WeatherAIPredictResponse,
} from '@/lib/api';
import { I18nProvider } from '@/lib/i18n';
import ParentPortal from './ParentPortal';

const apiMocks = vi.hoisted(() => ({
  listAreaProvinces: vi.fn(),
  getPublicWeatherAIOptions: vi.fn(),
  getPublicDiseaseKnowledge: vi.fn(),
  predictPublicParentRisk: vi.fn(),
  getAreaLocalRisks: vi.fn(),
  getAreaRecommendations: vi.fn(),
  getPublicPublishedMedicalKnowledge: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/api')>(),
  ...apiMocks,
}));

function ranking(): WeatherAIDiseaseRanking {
  return {
    rank: 1,
    disease_id: '17',
    disease_name: 'Viêm dạ dày ruột',
    disease_group_id: '17',
    disease_group_name: 'Viêm dạ dày ruột',
    report_group_code: 'A09',
    ranking_score: 0.91,
    tier1: {
      available: true,
      summary_vi: 'Mưa đang góp phần làm nhóm bệnh này được xếp cao hơn.',
      positive_factors: [{
        feature: 'rain_sum_7d',
        label_vi: 'Lượng mưa trong 7 ngày gần đây',
        category: 'WEATHER',
        window: '7D',
        input_value: 42,
        shap_value: 0.8,
        direction: 'UP',
        weather_factor: 'precipitation',
      }],
      negative_factors: [],
    },
    tier2: {
      available: true,
      evidence_status: 'SUPPORTED',
      explanation_short_vi: 'LEGACY TIER 2 MUST NOT RENDER',
      limitations_vi: 'Legacy limitations.',
      sources: [{ title: 'Legacy', organization: 'Legacy org', url: 'https://example.org', year: 2020 }],
    },
  };
}

function weatherResponse(): WeatherAIPredictResponse {
  const row = ranking();
  return {
    message: 'ok',
    context: {
      age_group: '1-5 tuổi',
      gender: 'Nam',
      anchor_date: '2026-08-23',
      horizon: '14D',
      top_k: 5,
      ranking_universe: 221,
    },
    input: { age_group: '1-5 tuổi', gender: 'Nam', top_k: 5 },
    weather: { features: { temp_mean_today: 30, humidity_mean_today: 80 } },
    predictions: [row],
    top_risks: [row],
    model: {
      model_type: 'LightGBM',
      horizon: '14D',
      with_weather: true,
      model_count: 221,
      score_semantics: 'ranking',
    },
    runtime_ms: {},
    disclaimer: 'Thông tin không thay thế chẩn đoán của bác sĩ.',
  };
}

const publishedItem: PublishedMedicalKnowledgeItem = {
  disease_group_id: '17',
  factor_type: 'WEATHER',
  factor_key: 'precipitation',
  factor_value: null,
  weather_factor: 'precipitation',
  revision_id: 6,
  knowledge_type: 'REVIEWED',
  warning: null,
  evidence_level: 'SUPPORTED',
  evidence_scope: 'PARTIAL_GROUP',
  short_explanation_vi: 'PUBLISHED V1 TIER 2 CONTENT',
  detailed_explanation_vi: 'Chi tiết V1 đã được nhân viên y tế duyệt.',
  limitations_vi: 'Không suy ra quan hệ nhân quả hoặc nguy cơ cá nhân.',
  sources: [{
    title: 'A reviewed PubMed source',
    journal: 'Journal',
    publication_year: 2025,
    pmid: '12345678',
    doi: null,
    pmcid: null,
    url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
  }],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

async function renderAndPredict() {
  render(<I18nProvider><ParentPortal /></I18nProvider>);
  const province = await screen.findByTestId('province-combobox-trigger');
  fireEvent.click(province);
  fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
  const submit = screen.getByTestId('parent-predict-submit');
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  await screen.findByText('Viêm dạ dày ruột');
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.listAreaProvinces.mockResolvedValue([{
    code: 'HCM',
    name: 'TP.HCM',
    latitude: 10.78,
    longitude: 106.69,
    is_active: true,
  }]);
  apiMocks.getPublicWeatherAIOptions.mockResolvedValue({
    age_groups: ['1-5 tuổi'],
    genders: ['Nam'],
    disease_catalog: [],
    ranking_universe: 221,
  });
  apiMocks.getPublicDiseaseKnowledge.mockResolvedValue([{
    id: 1,
    disease_group: 'Viêm dạ dày ruột',
    title: 'Kiến thức chăm sóc',
    symptoms: 'Đau bụng; Tiêu chảy',
    warning_signs: 'Đưa trẻ đi khám nếu có dấu hiệu mất nước.',
    prevention: 'Rửa tay; Ăn chín uống sôi',
    source: 'Nguồn nội bộ',
  }]);
  apiMocks.predictPublicParentRisk.mockResolvedValue(weatherResponse());
  apiMocks.getAreaLocalRisks.mockResolvedValue([]);
  apiMocks.getAreaRecommendations.mockResolvedValue({
    area: { province: null, district: null, ward: null },
    top_risks: [],
    recommendations: [],
  });
  apiMocks.getPublicPublishedMedicalKnowledge.mockResolvedValue({ items: [] });
});

describe('Parent Published Medical Knowledge integration', () => {
  it('renders ranking and Tier 1 first, then attaches only matching published V1 content', async () => {
    apiMocks.getPublicPublishedMedicalKnowledge.mockResolvedValue({
      items: [
        publishedItem,
        { ...publishedItem, disease_group_id: '99', revision_id: 88, short_explanation_vi: 'WRONG DISEASE CONTENT' },
        { ...publishedItem, weather_factor: 'humidity', revision_id: 89, short_explanation_vi: 'WRONG FACTOR CONTENT' },
      ],
    });

    await renderAndPredict();

    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeVisible();
    expect(screen.getByLabelText('Tóm tắt nhanh')).toBeVisible();
    expect(screen.getByLabelText('Hướng dẫn dành cho phụ huynh')).toBeVisible();
    expect(screen.getByLabelText('Khi nào cần đưa trẻ đi khám')).toBeVisible();
    const expandable = await screen.findByText('Giải thích y khoa chi tiết');
    expect(expandable.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(expandable);
    expect(await screen.findByText('PUBLISHED V1 TIER 2 CONTENT')).toBeVisible();
    expect(screen.queryByText('WRONG DISEASE CONTENT')).not.toBeInTheDocument();
    expect(screen.queryByText('WRONG FACTOR CONTENT')).not.toBeInTheDocument();
    expect(screen.queryByText('LEGACY TIER 2 MUST NOT RENDER')).not.toBeInTheDocument();
    expect(apiMocks.getPublicPublishedMedicalKnowledge).toHaveBeenCalledWith([
      { disease_group_id: '17', factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null, weather_factor: 'precipitation' },
    ]);
    expect(screen.getByText('Đau bụng')).toBeVisible();
    expect(screen.getByText('Rửa tay')).toBeVisible();
    expect(screen.getByText(/Đưa trẻ đi khám nếu có dấu hiệu mất nước/)).toBeVisible();
    expect(screen.queryByRole('button', { name: /duyệt|publish|xuất bản|chỉnh sửa/i })).not.toBeInTheDocument();
  });

  it('keeps ranking, Tier 1, and care guidance normal when no publication exists', async () => {
    await renderAndPredict();

    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeVisible();
    expect(screen.queryByRole('region', { name: 'Giải thích y khoa' })).not.toBeInTheDocument();
    expect(screen.getByText('Ăn chín uống sôi')).toBeVisible();
  });

  it('does not block ranking or Tier 1 while the optional Tier-2 request is pending', async () => {
    const pending = deferred<{ items: PublishedMedicalKnowledgeItem[] }>();
    apiMocks.getPublicPublishedMedicalKnowledge.mockReturnValue(pending.promise);

    await renderAndPredict();

    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Đang tải giải thích y khoa bổ sung');
    pending.resolve({ items: [] });
    await waitFor(() => expect(screen.queryByText(/Đang tải giải thích y khoa bổ sung/)).not.toBeInTheDocument());
  });

  it.each([
    ['HTTP 500', new Error('500 internal traceback')],
    ['network timeout', new TypeError('network timeout')],
  ])('isolates a Tier-2 %s failure from Parent prediction and Tier 1', async (_case, failure) => {
    apiMocks.getPublicPublishedMedicalKnowledge.mockRejectedValue(failure);

    await renderAndPredict();

    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeVisible();
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(screen.queryByText(/500 internal traceback|network timeout/i)).not.toBeInTheDocument();
  });

  it('preserves the existing Parent prediction error behavior', async () => {
    apiMocks.predictPublicParentRisk.mockRejectedValue(new TypeError('offline'));
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    expect(await screen.findByText(/Không thể kết nối hệ thống dự đoán/)).toBeVisible();
    expect(apiMocks.getPublicPublishedMedicalKnowledge).not.toHaveBeenCalled();
  });

  it('removes Parent Tier 2 after mocked Unpublish state while preserving ranking and Tier 1', async () => {
    apiMocks.getPublicPublishedMedicalKnowledge
      .mockResolvedValueOnce({ items: [publishedItem] })
      .mockResolvedValueOnce({ items: [] });
    await renderAndPredict();
    fireEvent.click(await screen.findByText('Giải thích y khoa chi tiết'));
    expect(await screen.findByText('PUBLISHED V1 TIER 2 CONTENT')).toBeVisible();

    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.getPublicPublishedMedicalKnowledge).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('PUBLISHED V1 TIER 2 CONTENT')).not.toBeInTheDocument());
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa trong 7 ngày gần đây')).toBeVisible();
  });
});
