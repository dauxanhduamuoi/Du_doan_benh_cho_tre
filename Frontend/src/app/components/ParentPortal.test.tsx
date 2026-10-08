import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
    weather: { features: { temperature_mean_current: 30, humidity_mean_current: 80 } },
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

async function renderAndPredict(count = 5) {
  render(<I18nProvider><ParentPortal /></I18nProvider>);
  const province = await screen.findByTestId('province-combobox-trigger');
  fireEvent.click(province);
  fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
  const submit = screen.getByTestId('parent-predict-submit');
  await waitFor(() => expect(submit).toBeEnabled());
  if (count !== 5) fireEvent.change(screen.getByLabelText('Hiển thị số lượng nhóm bệnh'), { target: { value: String(count) } });
  fireEvent.click(submit);
  await screen.findByText('Viêm dạ dày ruột');
}

async function openReferences() {
  const summary = await screen.findByText(/^Xem tài liệu tham khảo \(\d+\)$/);
  if (!summary.closest('details')?.open) fireEvent.click(summary);
}

function multipleGroups(count: number): WeatherAIPredictResponse {
  const response = weatherResponse();
  response.context.top_k = count;
  response.input.top_k = count;
  response.predictions = Array.from({ length: count }, (_, index) => ({
    ...ranking(), rank: index + 1, disease_id: String(17 + index), disease_group_id: String(17 + index),
    disease_name: index === 0 ? ranking().disease_name : `Nhóm bệnh thử ${index + 1}`,
    disease_group_name: index === 0 ? ranking().disease_name : `Nhóm bệnh thử ${index + 1}`,
  }));
  response.top_risks = response.predictions;
  return response;
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
    fireEvent.click(screen.getByText('Xem chi tiết giải thích mô hình'));
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
    expect(await screen.findByRole('alert')).toHaveTextContent(/Không thể kết nối hệ thống dự đoán/);
    expect(screen.getByRole('alert').querySelector('span')).toHaveClass('min-w-0', '[overflow-wrap:anywhere]');
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
    fireEvent.click(screen.getByText('Xem chi tiết giải thích mô hình'));
    expect(screen.getByText('Mưa / giáng thủy trong 7 ngày kết thúc ngày 23/08/2026')).toBeVisible();
  });
});

describe('Parent summary and form accessibility', () => {
  it('renders current runtime weather fields and Unicode units despite conflicting old aliases', async () => {
    const response = weatherResponse();
    response.weather.features = {
      temperature_mean_current: 31.5, humidity_mean_current: 82,
      temp_mean_today: 99, humidity_mean_today: 12,
    };
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    await renderAndPredict();
    expect(screen.getByText('31.5°C')).toBeVisible();
    expect(screen.getByText('82%')).toBeVisible();
    expect(screen.queryByText('99°C')).not.toBeInTheDocument();
    expect(screen.queryByText('12%')).not.toBeInTheDocument();
    expect(screen.queryByText(/\?C/)).not.toBeInTheDocument();
  });

  it('does not fall back to unsupported old weather keys', async () => {
    const response = weatherResponse();
    response.weather.features = { temp_mean_today: 99, humidity_mean_today: 12 };
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    await renderAndPredict();
    expect(screen.getByText('-°C')).toBeVisible();
    expect(screen.getByText('-%')).toBeVisible();
    expect(screen.queryByText('99°C')).not.toBeInTheDocument();
    expect(screen.queryByText('12%')).not.toBeInTheDocument();
  });

  it('uses Parent-facing empty guidance without import instructions', async () => {
    apiMocks.getPublicDiseaseKnowledge.mockResolvedValue([]);
    await renderAndPredict();
    expect(screen.getByText('Hiện chưa có hướng dẫn bổ sung cho mục này.')).toBeVisible();
    expect(screen.getByText('Hiện chưa có thông tin triệu chứng cho nhóm bệnh này.')).toBeVisible();
    expect(screen.getByLabelText('Hướng dẫn dành cho phụ huynh')).not.toHaveTextContent(/import|upload|admin/i);
    expect(screen.getByTestId('parent-disease-card')).not.toHaveTextContent(/import|upload|admin/i);
  });

  it('labels controls and exposes province disclosure, search and selection state', async () => {
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    const trigger = await screen.findByTestId('province-combobox-trigger');
    expect(screen.getByLabelText('Tỉnh/thành phố')).toBe(trigger);
    for (const label of ['Độ tuổi', 'Giới tính', 'Hiển thị số lượng nhóm bệnh']) {
      expect(screen.getByRole('combobox', { name: label })).toBe(screen.getByLabelText(label));
    }
    expect(screen.getByRole('group', { name: 'Chọn khu vực' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Tự chọn' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Dùng định vị' })).toHaveAttribute('aria-pressed', 'false');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const panel = document.getElementById(trigger.getAttribute('aria-controls')!);
    expect(panel).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Tìm tỉnh/thành phố...' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(screen.getByRole('button', { name: 'TP.HCM' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Dùng định vị' }));
    expect(screen.getByRole('button', { name: 'Dùng định vị' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Tự chọn' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps full long disease and disclaimer text with local wrapping', async () => {
    const longName = 'TênNhómBệnh'.repeat(40);
    const disclaimer = 'LưuÝDài'.repeat(50);
    const response = weatherResponse();
    response.predictions[0].disease_name = longName;
    response.disclaimer = disclaimer;
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    expect(await screen.findByRole('heading', { name: longName })).toHaveClass('[overflow-wrap:anywhere]');
    expect(screen.getByText(disclaimer)).toHaveClass('min-w-0', '[overflow-wrap:anywhere]');
    expect(screen.getByLabelText('Tóm tắt nhanh')).toHaveTextContent(longName);
  });
});

describe('Parent compact result navigation', () => {
  it('groups child controls on the left and location/weather on the right with neutral branding', async () => {
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    await screen.findByTestId('province-combobox-trigger');
    const child = screen.getByRole('region', { name: 'Thông tin của trẻ' });
    const location = screen.getByRole('region', { name: 'Khu vực / vị trí' });
    expect(within(child).getByLabelText('Độ tuổi')).toBeVisible();
    expect(within(child).getByLabelText('Giới tính')).toBeVisible();
    const count = within(child).getByLabelText('Hiển thị số lượng nhóm bệnh');
    expect(within(count).getAllByRole('option').map((option) => option.textContent)).toEqual(['5 nhóm', '10 nhóm', '20 nhóm']);
    expect(within(location).getByLabelText('Tỉnh/thành phố')).toBeVisible();
    expect(within(location).getByText('Nhiệt độ')).toBeVisible();
    expect(child.compareDocumentPosition(location) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.body).not.toHaveTextContent(/Lightning\s*Fox\s*SD|Top (5|10|20)/i);
  });

  it.each([5, 10, 20])('navigates exactly %i groups in backend order without extra API requests', async (count) => {
    apiMocks.predictPublicParentRisk.mockResolvedValue(multipleGroups(count));
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    fireEvent.change(screen.getByLabelText('Hiển thị số lượng nhóm bệnh'), { target: { value: String(count) } });
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await screen.findByText(`Nhóm 1 / ${count}`);
    expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledWith(expect.objectContaining({ top_k: count }));
    expect(screen.getByRole('button', { name: 'Nhóm trước' })).toBeDisabled();
    for (let index = 0; index < count; index += 1) {
      expect(screen.getAllByTestId('parent-disease-card')).toHaveLength(1);
      expect(screen.getByLabelText(`Xếp hạng ${index + 1}`)).toBeVisible();
      if (index < count - 1) fireEvent.click(screen.getByRole('button', { name: 'Nhóm tiếp theo' }));
    }
    expect(screen.getByText(`Nhóm ${count} / ${count}`)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Nhóm tiếp theo' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Nhóm trước' }));
    expect(screen.getByText(`Nhóm ${count - 1} / ${count}`)).toBeVisible();
    expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1);
    expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalledTimes(1);
  });

  it('starts collapsed, opens model details, and resets details on changing the displayed group', async () => {
    apiMocks.predictPublicParentRisk.mockResolvedValue(multipleGroups(5));
    await renderAndPredict();
    const summary = screen.getByText('Xem chi tiết giải thích mô hình');
    const explanation = screen.getByLabelText('Giải thích đóng góp của mô hình');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(explanation).not.toBeVisible();
    expect(screen.getByText('Đau bụng')).toBeVisible();
    expect(screen.getByLabelText('Khi nào cần đưa trẻ đi khám')).toBeVisible();
    fireEvent.click(summary);
    expect(summary.closest('details')).toHaveAttribute('open');
    expect(explanation).toBeVisible();
    expect(explanation).toHaveTextContent('Tổng lượng mưa trong 7 ngày kết thúc ngày 23/08/2026 là 42 mm.');
    fireEvent.click(summary);
    expect(explanation).not.toBeVisible();
    fireEvent.click(summary);
    fireEvent.click(screen.getByRole('button', { name: 'Nhóm tiếp theo' }));
    expect(screen.getByText('Xem chi tiết giải thích mô hình').closest('details')).not.toHaveAttribute('open');
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).not.toBeVisible();
  });

  it('resets navigation for a new prediction with fewer groups', async () => {
    apiMocks.predictPublicParentRisk.mockResolvedValue(multipleGroups(20));
    await renderAndPredict(20);
    for (let index = 1; index < 20; index += 1) fireEvent.click(screen.getByRole('button', { name: 'Nhóm tiếp theo' }));
    apiMocks.predictPublicParentRisk.mockResolvedValue(multipleGroups(5));
    fireEvent.change(screen.getByLabelText('Hiển thị số lượng nhóm bệnh'), { target: { value: '5' } });
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    expect(await screen.findByText('Nhóm 1 / 5')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Nhóm trước' })).toBeDisabled();
    expect(screen.getByLabelText('Xếp hạng 1')).toBeVisible();
  });

  it('retains the selected group when references arrive late and matches only its references', async () => {
    const pending = deferred<{ items: TrustedReferenceItem[] }>();
    apiMocks.predictPublicParentRisk.mockResolvedValue(multipleGroups(5));
    apiMocks.getPublicTrustedReferences.mockReturnValue(pending.promise);
    await renderAndPredict();
    fireEvent.click(screen.getByRole('button', { name: 'Nhóm tiếp theo' }));
    await act(async () => pending.resolve({ items: [{ ...referenceItem, selector: { ...referenceSelector, disease_group_id: '18' } }] }));
    expect(screen.getByText('Nhóm 2 / 5')).toBeVisible();
    expect(screen.getByLabelText('Xếp hạng 2')).toBeVisible();
    const title = screen.getByText('TRUSTED REFERENCE TITLE');
    expect(title).not.toBeVisible();
    await openReferences();
    expect(title).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Nhóm trước' }));
    expect(screen.queryByText('TRUSTED REFERENCE TITLE')).not.toBeInTheDocument();
    expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalledTimes(1);
  });

  it('shows all symptoms for bilingual disease names through the compact preview and expansion', async () => {
    const response = weatherResponse();
    response.predictions[0].disease_name = 'Viêm dạ dày ruột - Gastroenteritis';
    apiMocks.predictPublicParentRisk.mockResolvedValue(response);
    apiMocks.getPublicDiseaseKnowledge.mockResolvedValue([{
      id: 1, disease_group: 'Viêm dạ dày ruột', title: 'Kiến thức chăm sóc',
      symptoms: 'Đau bụng; Tiêu chảy; Nôn; Sốt; Mệt mỏi; Chán ăn', prevention: null,
    }]);
    await renderAndPredict();
    expect(screen.getByText('Đau bụng')).toBeVisible();
    expect(screen.getByText('Tiêu chảy')).toBeVisible();
    expect(screen.getByText('Chán ăn')).not.toBeVisible();
    fireEvent.click(screen.getByText(/^Xem thêm: triệu chứng/));
    for (const symptom of ['Nôn', 'Sốt', 'Mệt mỏi', 'Chán ăn']) expect(screen.getByText(symptom)).toBeVisible();
    expect(screen.queryByText('Hiện chưa có thông tin triệu chứng cho nhóm bệnh này.')).not.toBeInTheDocument();
  });

  it.each([null, undefined, '   '])('shows a clear symptom fallback for missing content: %s', async (symptoms) => {
    apiMocks.getPublicDiseaseKnowledge.mockResolvedValue([{
      id: 1, disease_group: 'Viêm dạ dày ruột', title: 'Kiến thức chăm sóc', symptoms,
    }]);
    await renderAndPredict();
    expect(screen.getByText('Hiện chưa có thông tin triệu chứng cho nhóm bệnh này.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Nhóm tiếp theo' })).toBeDisabled();
  });
});

describe('Parent prediction request races', () => {
  const oldRisks = [{ disease_group: 'Cúm', recent_cases: 777, risk_level: 'Cao' }];
  const currentRisks = [{ disease_group: 'Cúm', recent_cases: 25, risk_level: 'Cao' }];
  const oldAdvice = { recommendations: ['STALE RECOMMENDATION A'] };
  const currentAdvice = { recommendations: ['CURRENT RECOMMENDATION B'] };

  function currentResponse() {
    const response = weatherResponse();
    response.predictions = [{ ...ranking(), disease_id: '168', disease_group_id: '168', disease_name: 'Cúm', disease_group_name: 'Cúm' }];
    response.predictions[0].tier1.positive_factors = [{ ...ranking().tier1.positive_factors[0], input_value: 81 }];
    response.top_risks = response.predictions;
    response.weather.features = { temperature_mean_current: 31, humidity_mean_current: 82 };
    return response;
  }

  beforeEach(() => {
    apiMocks.listAreaProvinces.mockResolvedValue([
      { code: 'HCM', name: 'TP.HCM', latitude: 10.78, longitude: 106.69, is_active: true },
      { code: 'HAN', name: 'Hà Nội', latitude: 21.028, longitude: 105.834, is_active: true },
    ]);
    apiMocks.getPublicWeatherAIOptions.mockResolvedValue({ age_groups: ['1-5 tuổi', '6-10 tuổi'], genders: ['Nam', 'Nữ'], disease_catalog: [], ranking_universe: 221 });
    apiMocks.getPublicDiseaseKnowledge.mockResolvedValue([
      { id: 1, disease_group: 'Viêm dạ dày ruột', title: 'A', symptoms: 'STALE SYMPTOM A', prevention: 'STALE CARE A', warning_signs: 'STALE WARNING A' },
      { id: 2, disease_group: 'Cúm', title: 'B', symptoms: 'CURRENT SYMPTOM B', prevention: 'CURRENT CARE B', warning_signs: 'CURRENT WARNING B' },
    ]);
  });

  async function startOldRequest() {
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1));
  }

  function changeProvince() {
    fireEvent.click(screen.getByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'Hà Nội' }));
  }

  function assertCurrentResult() {
    const card = screen.getByTestId('parent-disease-card');
    expect(within(card).getByRole('heading', { name: 'Cúm' })).toBeVisible();
    expect(card).toHaveTextContent('25 ca');
    expect(card).toHaveTextContent('CURRENT SYMPTOM B');
    expect(card).toHaveTextContent('CURRENT CARE B');
    expect(card).toHaveTextContent('CURRENT WARNING B');
    expect(screen.getByLabelText('Giải thích đóng góp của mô hình')).toHaveTextContent('81 mm');
    expect(screen.getByText('CURRENT RECOMMENDATION B')).toBeVisible();
    expect(screen.getByText('31°C')).toBeVisible();
    expect(screen.queryByText('STALE RECOMMENDATION A')).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent('777');
    expect(card).not.toHaveTextContent('STALE SYMPTOM A');
  }

  it.each(['prediction', 'area'] as const)('does not restore any cleared state after location changes during the %s stage', async stage => {
    const prediction = deferred<WeatherAIPredictResponse>();
    const risks = deferred<typeof oldRisks>();
    const advice = deferred<typeof oldAdvice>();
    if (stage === 'prediction') apiMocks.predictPublicParentRisk.mockReturnValueOnce(prediction.promise);
    else {
      apiMocks.getAreaLocalRisks.mockReturnValueOnce(risks.promise);
      apiMocks.getAreaRecommendations.mockReturnValueOnce(advice.promise);
    }
    await startOldRequest();
    if (stage === 'area') await waitFor(() => expect(apiMocks.getAreaLocalRisks).toHaveBeenCalledTimes(1));
    changeProvince();
    await act(async () => { prediction.resolve(weatherResponse()); risks.resolve(oldRisks); advice.resolve(oldAdvice); });
    expect(screen.getByTestId('province-combobox-trigger')).toHaveTextContent('Hà Nội');
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    expect(screen.queryByText('STALE RECOMMENDATION A')).not.toBeInTheDocument();
    expect(apiMocks.getPublicTrustedReferences).not.toHaveBeenCalled();
    expect(screen.getByTestId('parent-predict-submit')).toBeEnabled();
    if (stage === 'prediction') {
      expect(apiMocks.getAreaLocalRisks).not.toHaveBeenCalled();
      expect(apiMocks.getAreaRecommendations).not.toHaveBeenCalled();
    }
  });

  it.each(['prediction', 'area'] as const)('keeps B prediction, area data, advice and guidance when A finishes last in its %s stage', async stage => {
    const old = deferred<WeatherAIPredictResponse>();
    const current = deferred<WeatherAIPredictResponse>();
    const risks = deferred<typeof oldRisks>();
    const advice = deferred<typeof oldAdvice>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(stage === 'prediction' ? old.promise : Promise.resolve(weatherResponse())).mockReturnValueOnce(current.promise);
    if (stage === 'area') {
      apiMocks.getAreaLocalRisks.mockReturnValueOnce(risks.promise);
      apiMocks.getAreaRecommendations.mockReturnValueOnce(advice.promise);
    }
    apiMocks.getAreaLocalRisks.mockResolvedValue(currentRisks);
    apiMocks.getAreaRecommendations.mockResolvedValue(currentAdvice);
    await startOldRequest();
    if (stage === 'area') await waitFor(() => expect(apiMocks.getAreaLocalRisks).toHaveBeenCalledTimes(1));
    changeProvince();
    expect(screen.getByTestId('parent-predict-submit')).toBeEnabled();
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await act(async () => current.resolve(currentResponse()));
    await screen.findByRole('heading', { name: 'Cúm' });
    assertCurrentResult();
    await act(async () => { old.resolve(weatherResponse()); risks.resolve(oldRisks); advice.resolve(oldAdvice); });
    assertCurrentResult();
    expect(apiMocks.predictPublicParentRisk).toHaveBeenNthCalledWith(2, expect.objectContaining({ latitude: 21.028, longitude: 105.834, top_k: 5 }));
    expect(apiMocks.getPublicTrustedReferences).toHaveBeenCalledTimes(1);
    expect(apiMocks.getPublicTrustedReferences.mock.calls[0][0]).toEqual([expect.objectContaining({ disease_group_id: '168' })]);
    if (stage === 'prediction') expect(apiMocks.getAreaLocalRisks).toHaveBeenCalledTimes(1);
  });

  it('ignores a stale prediction error after context invalidation', async () => {
    const old = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise);
    await startOldRequest(); changeProvince();
    await act(async () => old.reject(new Error('STALE ERROR A')));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('parent-predict-submit')).toBeEnabled();
  });

  it.each(['resolve', 'reject'] as const)('does not stop B loading or show A error when stale A %s runs finally', async outcome => {
    const old = deferred<WeatherAIPredictResponse>();
    const current = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    await startOldRequest(); changeProvince();
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(2));
    await act(async () => outcome === 'resolve' ? old.resolve(weatherResponse()) : old.reject(new Error('STALE ERROR A')));
    expect(screen.getByTestId('parent-predict-submit')).toBeDisabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    await act(async () => current.resolve(currentResponse()));
    expect(await screen.findByRole('heading', { name: 'Cúm' })).toBeVisible();
    expect(screen.getByTestId('parent-predict-submit')).toBeEnabled();
  });

  it('does not overwrite the current error with an older rejection', async () => {
    const old = deferred<WeatherAIPredictResponse>();
    const current = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    await startOldRequest(); changeProvince(); fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(2));
    await act(async () => current.reject(new Error('CURRENT ERROR B')));
    expect(await screen.findByRole('alert')).toHaveTextContent('CURRENT ERROR B');
    await act(async () => old.reject(new Error('STALE ERROR A')));
    expect(screen.getByRole('alert')).toHaveTextContent('CURRENT ERROR B');
  });

  it.each([['Độ tuổi', '6-10 tuổi'], ['Giới tính', 'Nữ'], ['Hiển thị số lượng nhóm bệnh', '20']])('invalidates pending prediction when %s changes', async (label, value) => {
    const old = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise);
    await startOldRequest();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    await act(async () => old.resolve(weatherResponse()));
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    expect(apiMocks.getAreaLocalRisks).not.toHaveBeenCalled();
    expect(apiMocks.getPublicTrustedReferences).not.toHaveBeenCalled();
    expect(screen.getByTestId('parent-predict-submit')).toBeEnabled();
  });

  it('invalidates pending prediction when leaving geolocation mode', async () => {
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: vi.fn(success => success({ coords: { latitude: 10.78, longitude: 106.69 } })) } });
    const old = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise);
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Dùng định vị' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Tự chọn' }));
    await act(async () => old.resolve(weatherResponse()));
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    expect(apiMocks.getAreaLocalRisks).not.toHaveBeenCalled();
  });

  it('invalidates a pending GPS prediction when refreshed coordinates arrive', async () => {
    const positions: PositionCallback[] = [];
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: vi.fn((success: PositionCallback) => positions.push(success)) } });
    const old = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise).mockResolvedValueOnce(currentResponse());
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    await waitFor(() => expect(screen.getByTestId('parent-predict-submit')).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Dùng định vị' }));
    act(() => positions[0]({ coords: { latitude: 10.78, longitude: 106.69 } } as GeolocationPosition));
    fireEvent.click(screen.getByRole('button', { name: 'Lấy lại định vị' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1));
    act(() => positions[1]({ coords: { latitude: 21.028, longitude: 105.834 } } as GeolocationPosition));
    await act(async () => old.resolve(weatherResponse()));
    expect(screen.queryByTestId('parent-disease-card')).not.toBeInTheDocument();
    expect(apiMocks.getAreaLocalRisks).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    expect(await screen.findByRole('heading', { name: 'Cúm' })).toBeVisible();
    expect(apiMocks.predictPublicParentRisk).toHaveBeenNthCalledWith(2, expect.objectContaining({ latitude: 21.028, longitude: 105.834 }));
  });

  it('does not invalidate a current manual prediction when an earlier GPS lookup finishes', async () => {
    const positions: PositionCallback[] = [];
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: vi.fn((success: PositionCallback) => positions.push(success)) } });
    const current = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(current.promise);
    render(<I18nProvider><ParentPortal /></I18nProvider>);
    await waitFor(() => expect(screen.getByTestId('parent-predict-submit')).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Dùng định vị' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tự chọn' }));
    fireEvent.click(screen.getByRole('button', { name: 'Hà Nội' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1));
    act(() => positions[0]({ coords: { latitude: 10.78, longitude: 106.69 } } as GeolocationPosition));
    expect(screen.getByTestId('parent-predict-submit')).toBeDisabled();
    await act(async () => current.resolve(currentResponse()));
    expect(await screen.findByRole('heading', { name: 'Cúm' })).toBeVisible();
    expect(screen.getByTestId('province-combobox-trigger')).toHaveTextContent('Hà Nội');
    expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledWith(expect.objectContaining({ latitude: 21.028, longitude: 105.834 }));
  });

  it('ignores prediction completion after unmount', async () => {
    const old = deferred<WeatherAIPredictResponse>();
    apiMocks.predictPublicParentRisk.mockReturnValueOnce(old.promise);
    const view = render(<I18nProvider><ParentPortal /></I18nProvider>);
    fireEvent.click(await screen.findByTestId('province-combobox-trigger'));
    fireEvent.click(screen.getByRole('button', { name: 'TP.HCM' }));
    fireEvent.click(screen.getByTestId('parent-predict-submit'));
    await waitFor(() => expect(apiMocks.predictPublicParentRisk).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => old.resolve(weatherResponse()));
    expect(apiMocks.getAreaLocalRisks).not.toHaveBeenCalled();
    expect(apiMocks.getPublicTrustedReferences).not.toHaveBeenCalled();
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
    await openReferences();
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
    await openReferences();
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
    await openReferences();
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
    await openReferences();
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
