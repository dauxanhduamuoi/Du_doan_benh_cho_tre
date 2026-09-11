import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  AutoDiscoveryDiagnostics, AutoMedicalKnowledgeJob, AutoMedicalKnowledgeOverview,
  AutoMedicalKnowledgeRevision,
} from '@/lib/medicalKnowledgeApi';
import { getFactorPresentation } from '@/lib/medicalKnowledgeFactors';
import AutoMedicalKnowledgePanel from './AutoMedicalKnowledgePanel';

const mocks = vi.hoisted(() => ({
  overview: vi.fn(), settings: vi.fn(), visibility: vi.fn(), regenerate: vi.fn(),
}));

vi.mock('@/lib/medicalKnowledgeApi', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/medicalKnowledgeApi')>(),
  getAutoMedicalKnowledgeOverview: mocks.overview,
  updateAutoMedicalKnowledgeSettings: mocks.settings,
  setAutoMedicalKnowledgeTopicVisibility: mocks.visibility,
  regenerateAutoMedicalKnowledge: mocks.regenerate,
}));

const diagnostics: AutoDiscoveryDiagnostics = {
  attempt: 1, queries_run: 2, raw_results: 18, deduplicated: 14,
  disease_relevant: 7, factor_relevant: 4, pediatric_relevant: 3,
  usable_evidence: 3, selected_for_generation: 3, insufficient_reason: null,
  queries: ['("Influenza"[Title/Abstract]) AND ("humidity"[Title/Abstract])'],
  sources: [{ pmid: '123', title: 'Relevant source', decision: 'SELECTED', reason_code: 'SELECTED_FOR_GENERATION', stage: 'STRICT' }],
  pipeline_version: 'auto-medical-v2', failure: null,
};

function makeJob(overrides: Partial<AutoMedicalKnowledgeJob> = {}): AutoMedicalKnowledgeJob {
  return {
    id: 4, topic_id: 2, disease_group_id: '5', disease_group_name: 'Cúm mùa ở trẻ em',
    factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null,
    status: 'FAILED', attempt_count: 1, trigger_type: 'PARENT',
    created_at: '2026-08-28T09:00:00', started_at: null, finished_at: null,
    next_retry_at: null, last_error_code: 'LLM_PROVIDER_FAILED', is_current_attempt: true,
    legacy: false, pipeline_version: 'auto-medical-v2', history: [], diagnostics,
    ...overrides,
  };
}

function makeRevision(overrides: Partial<AutoMedicalKnowledgeRevision> = {}): AutoMedicalKnowledgeRevision {
  return {
    id: 8, topic_id: 2, disease_group_id: '5', disease_group_name: 'Cúm mùa ở trẻ em',
    factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null,
    weather_factor: 'precipitation', revision_number: 1, generation_status: 'READY',
    generation_mode: 'AI_FULL', auto_tier: 'STRICT', generation_method: 'AI',
    strict_failure_code: null, strict_failure_stage: null, fallback_reason_code: null,
    evidence_level: 'SUPPORTED', evidence_scope: 'PARTIAL_GROUP',
    short_explanation_vi: 'Mưa có thể liên quan đến thay đổi nguy cơ theo mùa.',
    detailed_explanation_vi: 'Nội dung chi tiết dựa trên bằng chứng đã chọn.',
    limitations_vi: 'Không dùng để chẩn đoán cá nhân.', is_visible: true,
    auto_display_eligible: true, topic_hidden_by_staff: false, topic_hidden_at: null,
    llm_model: 'model', prompt_version: 'auto-v2', generated_at: '2026-08-28T09:00:00',
    source_retrieved_at: '2026-08-28T08:00:00',
    sources: [{
      source_id: 3, title: 'Pediatric PubMed evidence', journal: 'Journal',
      publication_year: 2025, pmid: '40123456', doi: null,
      url: 'https://pubmed.ncbi.nlm.nih.gov/40123456/', trust_class: 'PUBMED',
      content_kind: 'ABSTRACT', source_role: 'PRIMARY', relevance_note: 'DIRECT',
      population_relevance: 'PEDIATRIC_DIRECT', population_note: 'Trẻ em.',
    }],
    diagnostics,
    ...overrides,
  };
}

function makeOverview(overrides: Partial<AutoMedicalKnowledgeOverview> = {}): AutoMedicalKnowledgeOverview {
  return {
    settings: { enabled: true, display_mode: 'REVIEWED_ONLY', auto_visible_default: true, basic_fallback_enabled: true },
    provider_cooldown: null, jobs: [makeJob()], revisions: [makeRevision()], ...overrides,
  };
}

async function settle() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe('factor presentation', () => {
  it.each([
    [{ factor_type: 'WEATHER', factor_key: 'temperature', factor_value: null }, 'Nhiệt độ', 'Thời tiết'],
    [{ factor_type: 'WEATHER', factor_key: 'humidity', factor_value: null }, 'Độ ẩm', 'Thời tiết'],
    [{ factor_type: 'AGE', factor_key: 'age_group', factor_value: '0–5 tuổi' }, 'Độ tuổi: 0–5 tuổi', 'Đặc điểm trẻ'],
    [{ factor_type: 'SEASONALITY', factor_key: 'season', factor_value: null }, 'Thời điểm trong năm', 'Yếu tố thời gian'],
  ] as const)('maps a raw selector to friendly Vietnamese labels %#', (selector, title, category) => {
    expect(getFactorPresentation(selector)).toMatchObject({ title, categoryLabel: category });
  });
});

describe('AutoMedicalKnowledgePanel disease-first UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const overview = makeOverview();
    mocks.overview.mockResolvedValue(overview);
    mocks.settings.mockResolvedValue(overview.settings);
    mocks.visibility.mockResolvedValue({ ok: true, topic_id: 2, message: 'ok' });
    mocks.regenerate.mockResolvedValue({ ok: true, job_id: 5, created: true, outcome: 'CREATED', job_status: 'QUEUED', message: 'Đã tạo yêu cầu mới.' });
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it('uses disease name as the group heading and ID as secondary metadata', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText('Cúm mùa ở trẻ em')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/Mã nhóm #5/).length).toBeGreaterThanOrEqual(2);
  });

  it('shows friendly factor labels instead of raw enums in the primary row', async () => {
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText('Mưa / lượng mưa')).length).toBeGreaterThanOrEqual(2);
    expect(container).not.toHaveTextContent('WEATHER · precipitation');
  });

  it('groups multiple topics under one disease section in each work area', async () => {
    const secondJob = makeJob({ id: 5, topic_id: 3, factor_key: 'humidity', status: 'READY', last_error_code: null });
    const secondRevision = makeRevision({ id: 9, topic_id: 3, factor_key: 'humidity', weather_factor: 'humidity' });
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob(), secondJob], revisions: [makeRevision(), secondRevision] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText('Cúm mùa ở trẻ em'))).toHaveLength(2);
    expect(screen.getAllByText('Mã nhóm #5 · 2 chủ đề')).toHaveLength(2);
    expect(screen.getAllByText('Độ ẩm').length).toBeGreaterThanOrEqual(2);
  });

  it('keeps different diseases in separate groups', async () => {
    const otherJob = makeJob({ id: 6, topic_id: 6, disease_group_id: '9', disease_group_name: 'Sốt xuất huyết', factor_key: 'humidity' });
    const otherRevision = makeRevision({ id: 10, topic_id: 6, disease_group_id: '9', disease_group_name: 'Sốt xuất huyết', factor_key: 'humidity' });
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob(), otherJob], revisions: [makeRevision(), otherRevision] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText('Sốt xuất huyết'))).toHaveLength(2);
    expect(screen.getAllByText(/Mã nhóm #9/)).toHaveLength(2);
  });

  it.each([
    ['Cúm mùa', true], ['5', true], ['lượng mưa', true], ['precipitation', true], ['WEATHER', true], ['không tồn tại', false],
  ])('searches disease, IDs and friendly/raw factor terms: %s', async (query, found) => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Xử lý và trạng thái');
    fireEvent.change(screen.getByLabelText('Tìm chủ đề Auto'), { target: { value: query } });
    if (found) expect(screen.queryByText('Không có tiến trình phù hợp bộ lọc.')).not.toBeInTheDocument();
    else expect(screen.getByText('Không có tiến trình phù hợp bộ lọc.')).toBeVisible();
  });

  it('searches a factor value', async () => {
    const age = makeJob({ factor_type: 'AGE', factor_key: 'age_group', factor_value: '0–5 tuổi' });
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [age], revisions: [] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.change(await screen.findByLabelText('Tìm chủ đề Auto'), { target: { value: '0-5 tuoi' } });
    expect(screen.getByText('Độ tuổi: 0–5 tuổi')).toBeVisible();
  });

  it('filters by job status locally', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Xử lý và trạng thái');
    const calls = mocks.overview.mock.calls.length;
    fireEvent.change(screen.getByLabelText('Lọc trạng thái Auto'), { target: { value: 'READY' } });
    expect(screen.getByText('Không có tiến trình phù hợp bộ lọc.')).toBeVisible();
    expect(mocks.overview).toHaveBeenCalledTimes(calls);
  });

  it.each([['STRICT', false], ['BASIC', true], ['INSUFFICIENT', true]] as const)('filters by tier %s', async (value, empty) => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Nội dung hiện tại');
    fireEvent.change(screen.getByLabelText('Lọc mức Auto'), { target: { value } });
    expect(Boolean(screen.queryByText('Chưa có nội dung Auto phù hợp bộ lọc.'))).toBe(empty);
  });

  it('filters by factor group', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Xử lý và trạng thái');
    fireEvent.change(screen.getByLabelText('Lọc nhóm yếu tố Auto'), { target: { value: 'AGE' } });
    expect(screen.getByText('Không có tiến trình phù hợp bộ lọc.')).toBeVisible();
  });

  it.each([['VISIBLE', false], ['HIDDEN', true], ['INELIGIBLE', true]] as const)('filters by visibility %s', async (value, empty) => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Nội dung hiện tại');
    fireEvent.change(screen.getByLabelText('Lọc hiển thị Auto'), { target: { value } });
    expect(Boolean(screen.queryByText('Chưa có nội dung Auto phù hợp bộ lọc.'))).toBe(empty);
  });

  it('presents Strict AI and Basic Safe Template tiers clearly', async () => {
    const basic = makeRevision({ id: 9, topic_id: 3, factor_key: 'humidity', auto_tier: 'BASIC', generation_mode: 'SAFE_FALLBACK', generation_method: 'SAFE_TEMPLATE', strict_failure_code: 'AUTO_OUTPUT_SCHEMA_INVALID', fallback_reason_code: 'CONTRACT_REPAIR_EXHAUSTED' });
    mocks.overview.mockResolvedValue(makeOverview({ revisions: [makeRevision(), basic] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Tự động – Kiểm tra nâng cao')).toBeVisible();
    expect(screen.getByText('Tự động – Giải thích cơ bản')).toBeVisible();
    expect(screen.getByText('Bản rút gọn an toàn')).toBeVisible();
    expect(screen.getByText(/hệ thống đang dùng giải thích cơ bản an toàn/i)).toBeVisible();
  });

  it('explains insufficient evidence without presenting a tier', async () => {
    const insufficientJob = makeJob({ status: 'INSUFFICIENT', last_error_code: null, diagnostics: { ...diagnostics, insufficient_reason: 'NO_FACTOR_RELEVANT_SOURCE' } });
    const insufficientRevision = makeRevision({ generation_status: 'INSUFFICIENT', auto_tier: null, short_explanation_vi: null, detailed_explanation_vi: null, evidence_level: 'INSUFFICIENT', auto_display_eligible: false, sources: [], diagnostics: insufficientJob.diagnostics });
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [insufficientJob], revisions: [insufficientRevision] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText(/Chưa tìm được tài liệu đánh giá trực tiếp yếu tố/)).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('Tự động – Kiểm tra nâng cao')).not.toBeInTheDocument();
  });

  it('keeps technical diagnostics collapsed and omits raw evidence bodies', async () => {
    const failure = { ...diagnostics, failure: { code: 'AUTO_OUTPUT_VALIDATION_FAILED', field: null, source_id: null, numeric_value: null, safe_detail: 'Safe detail only.', provider_error_class: 'ValidationError' } };
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob({ last_error_code: 'AUTO_OUTPUT_VALIDATION_FAILED', diagnostics: failure })] }));
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    const summary = await screen.findByText('Thông tin kỹ thuật');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(summary);
    expect(screen.getByText('Safe detail only.')).toBeVisible();
    expect(container).not.toHaveTextContent('full raw abstract body');
  });

  it('expands detailed content and linked sources on demand', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    const summary = await screen.findByText('Xem nội dung và nguồn');
    fireEvent.click(summary);
    expect(screen.getByText('Nội dung chi tiết dựa trên bằng chứng đã chọn.')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Pediatric PubMed evidence' })).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/40123456/');
    expect(screen.getByText(/PMID 40123456/)).toBeVisible();
  });

  it('hides a topic without regenerating it', async () => {
    const hidden = makeRevision({ topic_hidden_by_staff: true, is_visible: false, topic_hidden_at: '2026-09-09T09:00:00' });
    mocks.overview.mockResolvedValueOnce(makeOverview()).mockResolvedValue(makeOverview({ revisions: [hidden] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Ẩn khỏi phụ huynh' }));
    await waitFor(() => expect(mocks.visibility).toHaveBeenCalledWith('5', expect.objectContaining({ factor_key: 'precipitation' }), true));
    expect(await screen.findByText('Đã ẩn bởi nhân viên')).toBeVisible();
    expect(mocks.regenerate).not.toHaveBeenCalled();
  });

  it('lets visibility staff unhide without full management rights', async () => {
    const hiddenOverview = makeOverview({ revisions: [makeRevision({ topic_hidden_by_staff: true, is_visible: false })] });
    mocks.overview.mockResolvedValueOnce(hiddenOverview).mockResolvedValue(makeOverview());
    render(<AutoMedicalKnowledgePanel canManage={false} canManageVisibility />);
    fireEvent.click(await screen.findByRole('button', { name: 'Hiển thị lại' }));
    await waitFor(() => expect(mocks.visibility).toHaveBeenCalledWith('5', expect.any(Object), false));
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('regenerates the exact failed topic once while busy', async () => {
    let resolve!: (value: unknown) => void;
    mocks.regenerate.mockImplementation(() => new Promise((done) => { resolve = done; }));
    render(<AutoMedicalKnowledgePanel canManage />);
    const retry = await screen.findByRole('button', { name: 'Thử lại' });
    fireEvent.click(retry); fireEvent.click(retry);
    expect(mocks.regenerate).toHaveBeenCalledTimes(1);
    expect(mocks.regenerate).toHaveBeenCalledWith('5', expect.objectContaining({ factor_type: 'WEATHER', factor_key: 'precipitation' }));
    await act(async () => { resolve({ ok: true, created: true, message: 'ok' }); });
  });

  it.each(['QUEUED', 'SEARCHING', 'GENERATING'] as const)('disables revision regeneration while topic is %s', async (status) => {
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob({ status, last_error_code: null })] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByRole('button', { name: 'Tạo lại' })).toBeDisabled();
  });

  it('renders global OFF state without hiding existing content', async () => {
    mocks.overview.mockResolvedValue(makeOverview({ settings: { ...makeOverview().settings, enabled: false } }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/Auto đang tạm dừng/)).toBeVisible();
    expect(screen.getByText('Mưa có thể liên quan đến thay đổi nguy cơ theo mùa.')).toBeVisible();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('states clearly when Parent Auto display is globally off', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Auto đang tắt trên giao diện phụ huynh')).toBeVisible();
    expect(screen.queryByText('Đang hiển thị tự động')).not.toBeInTheDocument();
  });

  it('uses eligibility wording when Parent Auto fallback is enabled', async () => {
    mocks.overview.mockResolvedValue(makeOverview({ settings: { ...makeOverview().settings, display_mode: 'REVIEWED_WITH_AUTO_FALLBACK' } }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Đủ điều kiện hiển thị tự động')).toBeVisible();
  });

  it('renders Basic AI separately from Basic Safe Template', async () => {
    mocks.overview.mockResolvedValue(makeOverview({ revisions: [makeRevision({ auto_tier: 'BASIC', generation_mode: 'AI_FULL', generation_method: 'AI' })] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Tự động – Giải thích cơ bản')).toBeVisible();
    expect(screen.getByText('AI')).toBeVisible();
    expect(screen.queryByText('Bản rút gọn an toàn')).not.toBeInTheDocument();
  });

  it.each([
    ['READY', 'Hoàn thành'], ['FAILED', 'Có lỗi'], ['QUEUED', 'Đang chờ'],
    ['SEARCHING', 'Đang tìm tài liệu'], ['GENERATING', 'Đang tạo giải thích'],
  ] as const)('presents backend status %s with a friendly label', async (status, label) => {
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob({ status, last_error_code: status === 'FAILED' ? 'LLM_PROVIDER_FAILED' : null })] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    const processingArea = (await screen.findByText('Xử lý và trạng thái')).closest('section')!;
    expect(within(processingArea).getByText(label)).toBeVisible();
  });

  it('toggles persisted runtime state', async () => {
    const off = makeOverview({ settings: { ...makeOverview().settings, enabled: false } });
    mocks.overview.mockResolvedValueOnce(off).mockResolvedValue(makeOverview());
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByRole('switch'));
    await waitFor(() => expect(mocks.settings).toHaveBeenCalledWith({ enabled: true }));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });

  it('keeps staff view read-only', async () => {
    render(<AutoMedicalKnowledgePanel canManage={false} />);
    await screen.findByText('Auto Medical Knowledge');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Thử lại' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tạo lại' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Chế độ hiển thị Auto cho Parent')).toBeDisabled();
  });

  it('shows legacy history only after the explicit opt-in', async () => {
    const legacy = makeJob({ id: 3, is_current_attempt: false, legacy: true, pipeline_version: null });
    const current = makeJob({ id: 4, status: 'READY', last_error_code: null });
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [current, legacy] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Xử lý và trạng thái');
    expect(screen.queryByText('Lịch sử xử lý (1)')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Hiện lịch sử cũ'));
    expect(screen.getByText('Lịch sử xử lý (1)')).toBeVisible();
  });

  it('does not poll terminal current jobs', async () => {
    vi.useFakeTimers();
    render(<AutoMedicalKnowledgePanel canManage />);
    await settle();
    await act(async () => { await vi.advanceTimersByTimeAsync(12_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(1);
  });

  it('polls active work until it becomes terminal, then stops', async () => {
    vi.useFakeTimers();
    mocks.overview.mockResolvedValueOnce(makeOverview({ jobs: [makeJob({ status: 'QUEUED', last_error_code: null })] })).mockResolvedValueOnce(makeOverview({ jobs: [makeJob({ status: 'READY', last_error_code: null })] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    await settle();
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(2);
  });

  it('preserves the last confirmed state on transient poll failure', async () => {
    vi.useFakeTimers();
    mocks.overview.mockResolvedValueOnce(makeOverview({ jobs: [makeJob({ status: 'QUEUED', last_error_code: null })] })).mockRejectedValueOnce(new Error('network'));
    render(<AutoMedicalKnowledgePanel canManage />);
    await settle();
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getAllByText('Đang chờ').some((element) => element.tagName === 'SPAN')).toBe(true);
  });

  it('fails closed when overview cannot be loaded', async () => {
    mocks.overview.mockRejectedValue(new Error('unavailable'));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Không xác định được trạng thái dịch vụ Auto Medical Knowledge.');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('uses a responsive two-area layout without fixed card widths', async () => {
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Xử lý và trạng thái');
    expect(container.querySelector('.xl\\:grid-cols-2')).toBeInTheDocument();
    expect(container.innerHTML).not.toContain('w-[640px]');
  });

  it('renders long disease and content text without replacing the source-of-truth name', async () => {
    const longName = 'Bệnh hô hấp nhi khoa có tên rất dài dùng để kiểm tra khả năng co giãn của bố cục quản trị';
    const longText = 'Nội dung dài '.repeat(80);
    mocks.overview.mockResolvedValue(makeOverview({ jobs: [makeJob({ disease_group_name: longName })], revisions: [makeRevision({ disease_group_name: longName, short_explanation_vi: longText })] }));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect((await screen.findAllByText(longName))).toHaveLength(2);
    expect(screen.getByText((content) => content.startsWith('Nội dung dài Nội dung dài') && content.length > 500)).toBeVisible();
  });
});
