import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  PublishedMedicalKnowledgeItem,
  TrustedReferenceItem,
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
  getPublicTrustedReferences: vi.fn(),
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
  vi.resetAllMocks();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected network in Parent tests')));
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
  apiMocks.getPublicTrustedReferences.mockResolvedValue({ items: [] });
});

afterEach(() => {
  expect(apiMocks.getPublicPublishedMedicalKnowledge).not.toHaveBeenCalled();
  for (const [path] of vi.mocked(globalThis.fetch).mock.calls) {
    expect(path).toBe('/api/public/trusted-references');
  }
  vi.unstubAllGlobals();
});

describe('Parent legacy generated Medical Knowledge disconnect', () => {
  it.each(['REVIEWED', 'AUTO'] as const)('does not fetch or render %s generated prose or warnings', async (knowledge_type) => {
    apiMocks.getPublicPublishedMedicalKnowledge.mockResolvedValue({
      items: [{ ...publishedItem, knowledge_type, warning: 'OLD GENERATED WARNING' }],
    });
    await renderAndPredict();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('42 mm');
    expect(screen.getByLabelText('Hướng dẫn dành cho phụ huynh')).toBeVisible();
    expect(screen.getByLabelText('Khi nào cần đưa trẻ đi khám')).toBeVisible();
    expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalled();
    for (const text of [publishedItem.short_explanation_vi, publishedItem.detailed_explanation_vi,
      publishedItem.limitations_vi, 'OLD GENERATED WARNING', 'Giải thích y khoa chi tiết']) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('region', { name: 'Giải thích y khoa' })).not.toBeInTheDocument();
    expect(screen.queryByText('LEGACY TIER 2 MUST NOT RENDER')).not.toBeInTheDocument();
    expect(screen.getByText('Đau bụng')).toBeVisible();
    expect(screen.getByText('Rửa tay')).toBeVisible();
    expect(screen.getByText(/Đưa trẻ đi khám nếu có dấu hiệu mất nước/)).toBeVisible();
    expect(screen.queryByRole('button', { name: /duyệt|publish|xuất bản|chỉnh sửa/i })).not.toBeInTheDocument();
  });

  it('keeps deterministic explanation and care guidance without any publication request', async () => {
    await renderAndPredict();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa / giáng thủy trong 7 ngày kết thúc ngày 23/08/2026')).toBeVisible();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('Tổng lượng mưa trong 7 ngày kết thúc ngày 23/08/2026 là 42 mm.');
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('so với mức nền của model');
    expect(screen.getByLabelText('Tóm tắt nhanh')).toHaveTextContent('Các đặc trưng được chọn dưới đây mô tả đóng góp vào điểm');
    expect(screen.queryByText('Mưa đang góp phần làm nhóm bệnh này được xếp cao hơn.')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Giải thích y khoa' })).not.toBeInTheDocument();
    expect(screen.getByText('Ăn chín uống sôi')).toBeVisible();
  });

  it('never starts legacy loading even if the legacy service would stay pending', async () => {
    const pending = deferred<{ items: PublishedMedicalKnowledgeItem[] }>();
    apiMocks.getPublicPublishedMedicalKnowledge.mockReturnValue(pending.promise);
    await renderAndPredict();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('42 mm');
    expect(screen.queryByText(/Đang tải giải thích y khoa bổ sung/)).not.toBeInTheDocument();
    await act(async () => pending.resolve({ items: [publishedItem] }));
    expect(screen.queryByText(publishedItem.short_explanation_vi)).not.toBeInTheDocument();
  });

  it('preserves generic care guidance and area data', async () => {
    apiMocks.getAreaLocalRisks.mockResolvedValue([{
      disease_group: 'Viêm dạ dày ruột', recent_cases: 12, risk_level: 'Cao',
      period_from: '2026-09-01', period_to: '2026-09-30',
    }]);
    await renderAndPredict();
    expect(screen.getByText(/Dữ liệu khu vực: Cao/)).toBeVisible();
    expect(screen.getByText(/12 ca/)).toBeVisible();
    expect(screen.getByText(/2026-09-01/)).toBeVisible();
    expect(screen.getByText('Ăn chín uống sôi')).toBeVisible();
    expect(screen.getByText('Tiêu chảy')).toBeVisible();
    expect(apiMocks.getPublicDiseaseKnowledge).toHaveBeenCalledTimes(1);
    expect(apiMocks.getAreaLocalRisks).toHaveBeenCalledWith({ provinceCode: 'HCM', limit: 5 });
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

  it('retains no legacy content across clearing and a new prediction', async () => {
    apiMocks.getPublicPublishedMedicalKnowledge.mockResolvedValue({ items: [publishedItem] });
    await renderAndPredict();
    fireEvent.click(screen.getByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('parent-predict-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('PUBLISHED V1 TIER 2 CONTENT')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByText('Mưa / giáng thủy trong 7 ngày kết thúc ngày 23/08/2026')).toBeVisible();
  });
});

const referenceSelector = {
  disease_group_id: '17', factor_type: 'WEATHER' as const, factor_key: 'precipitation', factor_value: null,
};
const referenceItem: TrustedReferenceItem = {
  selector: referenceSelector,
  references: [{ source_id: 10, title: 'TRUSTED REFERENCE TITLE', provider_id: 'WHO', external_id: 'stored-id',
    source_type: 'WHO', source_kind: 'HEALTH_GUIDANCE', journal: 'Stored journal', publication_year: 2025,
    original_url: 'https://example.org/original-source' }],
};

describe('Parent Trusted References optional integration', () => {
  it('uses the actual read-only client and never requests the legacy published endpoint', async () => {
    const actualApi = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
    apiMocks.getPublicTrustedReferences.mockImplementation(actualApi.getPublicTrustedReferences);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [referenceItem] }) });
    vi.stubGlobal('fetch', fetchMock);
    await renderAndPredict();
    expect(await screen.findByText('TRUSTED REFERENCE TITLE')).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/public/trusted-references', expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ items: [referenceSelector] });
    expect(apiMocks.getPublicPublishedMedicalKnowledge).not.toHaveBeenCalled();
  });

  it('renders the prediction before references and keeps deterministic SHAP text unchanged', async () => {
    const pending = deferred<{ items: TrustedReferenceItem[] }>();
    apiMocks.getPublicTrustedReferences.mockReturnValue(pending.promise);
    await renderAndPredict();
    expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalledWith([referenceSelector]);
    expect(apiMocks.getPublicPublishedMedicalKnowledge).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Tài liệu tham khảo' })).not.toBeInTheDocument();
    const explanationBefore = screen.getByLabelText('Giải thích đóng góp của mô hình').textContent;
    expect(explanationBefore).toContain('Tổng lượng mưa trong 7 ngày kết thúc ngày 23/08/2026 là 42 mm.');
    expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledWith({
      age_group: '1-5 tuổi', gender: 'Nam', top_k: 5, latitude: 10.78, longitude: 106.69, timezone: 'Asia/Ho_Chi_Minh',
    });
    await act(async () => pending.resolve({ items: [referenceItem] }));
    expect(screen.getByText('TRUSTED REFERENCE TITLE')).toBeVisible();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình').textContent).toBe(explanationBefore);
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
  });

  it.each(['timeout', 'HTTP 422', 'HTTP 500'])('isolates a reference %s failure without changing Model Explanation', async (reason) => {
    apiMocks.getPublicTrustedReferences.mockRejectedValue(new Error(reason));
    await renderAndPredict();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('so với mức nền của model');
    expect(screen.queryByRole('region', { name: 'Tài liệu tham khảo' })).not.toBeInTheDocument();
    expect(screen.queryByText(reason)).not.toBeInTheDocument();
  });

  it('isolates malformed reference payloads', async () => {
    apiMocks.getPublicTrustedReferences.mockResolvedValue({ items: null });
    await renderAndPredict();
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('42 mm');
    expect(screen.queryByRole('region', { name: 'Tài liệu tham khảo' })).not.toBeInTheDocument();
  });

  it('maps only exact AGE, SEX and WEATHER selectors to the disease card', async () => {
    const response = weatherResponse();
    response.predictions[0].tier1.positive_factors.push(
      { feature: 'age_group', label_vi: 'Nhóm tuổi', category: 'DEMOGRAPHIC', window: 'NONE', input_value: '1-5 tuổi', shap_value: 0.5, direction: 'UP' },
      { feature: 'gender', label_vi: 'Giới tính', category: 'DEMOGRAPHIC', window: 'NONE', input_value: 'Nam', shap_value: 0.4, direction: 'UP' },
    );
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    const age = { ...referenceSelector, factor_type: 'AGE' as const, factor_key: 'age_group', factor_value: '1-5 tuổi' };
    const sex = { ...referenceSelector, factor_type: 'SEX' as const, factor_key: 'gender', factor_value: 'Nam' };
    const item = (selector: TrustedReferenceItem['selector'], title: string, source_id: number): TrustedReferenceItem => ({
      selector, references: [{ ...referenceItem.references[0], source_id, title }],
    });
    apiMocks.getPublicTrustedReferences.mockResolvedValue({ items: [
      item(age, 'EXACT AGE SOURCE', 1), item({ ...age, factor_value: '6-10 tuổi' }, 'WRONG AGE SOURCE', 2),
      item(sex, 'EXACT SEX SOURCE', 3), item({ ...sex, factor_value: 'Nữ' }, 'WRONG SEX SOURCE', 4),
      item(referenceSelector, 'EXACT WEATHER SOURCE', 5), item({ ...referenceSelector, factor_value: '42' }, 'WRONG WEATHER VALUE', 6),
      item({ ...referenceSelector, disease_group_id: '99' }, 'WRONG DISEASE SOURCE', 7),
      item({ ...referenceSelector, factor_key: 'humidity' }, 'WRONG WEATHER KEY', 8),
    ] });
    await renderAndPredict();
    expect(await screen.findByText('EXACT AGE SOURCE')).toBeVisible();
    expect(screen.getByText('EXACT SEX SOURCE')).toBeVisible();
    expect(screen.getByText('EXACT WEATHER SOURCE')).toBeVisible();
    expect(screen.queryByText(/WRONG AGE|WRONG SEX|WRONG WEATHER|WRONG DISEASE SOURCE/)).not.toBeInTheDocument();
  });

  it('never attaches an old reference response after a newer prediction starts', async () => {
    const oldReferences = deferred<{ items: TrustedReferenceItem[] }>();
    const newerPrediction = deferred<WeatherAIPredictResponse>();
    apiMocks.getPublicTrustedReferences.mockReturnValueOnce(oldReferences.promise).mockResolvedValueOnce({
      items: [{ ...referenceItem, references: [{ ...referenceItem.references[0], title: 'NEW REFERENCE' }] }],
    });
    await renderAndPredict();
    await waitFor(() => expect(screen.getByTestId('parent-predict-submit')).toBeEnabled());
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(newerPrediction.promise);
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await act(async () => oldReferences.resolve({ items: [referenceItem] }));
    expect(screen.queryByText('TRUSTED REFERENCE TITLE')).not.toBeInTheDocument();
    await act(async () => newerPrediction.resolve(weatherResponse()));
    expect(await screen.findByText('NEW REFERENCE')).toBeVisible();
    expect(screen.queryByText('TRUSTED REFERENCE TITLE')).not.toBeInTheDocument();
  });

  it('ignores references that finish after result clearing', async () => {
    const pending = deferred<{ items: TrustedReferenceItem[] }>();
    apiMocks.getPublicTrustedReferences.mockReturnValue(pending.promise);
    await renderAndPredict();
    fireEvent.click(screen.getByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    await act(async () => pending.resolve({ items: [referenceItem] }));
    expect(screen.queryByText('TRUSTED REFERENCE TITLE')).not.toBeInTheDocument();
  });

  it('does not fetch references when no positive canonical selector exists', async () => {
    const response = weatherResponse();
    response.predictions[0].tier1.positive_factors = [];
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    await renderAndPredict();
    expect(apiMocks.getPublicTrustedReferences).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
  });
});
