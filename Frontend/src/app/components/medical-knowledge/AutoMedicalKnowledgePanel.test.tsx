import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutoMedicalKnowledgeOverview } from '@/lib/medicalKnowledgeApi';
import AutoMedicalKnowledgePanel from './AutoMedicalKnowledgePanel';

const mocks = vi.hoisted(() => ({
  overview: vi.fn(),
  settings: vi.fn(),
  visibility: vi.fn(),
  retry: vi.fn(),
  regenerate: vi.fn(),
}));

vi.mock('@/lib/medicalKnowledgeApi', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/medicalKnowledgeApi')>(),
  getAutoMedicalKnowledgeOverview: mocks.overview,
  updateAutoMedicalKnowledgeSettings: mocks.settings,
  setAutoMedicalKnowledgeVisibility: mocks.visibility,
  retryAutoMedicalKnowledgeJob: mocks.retry,
  regenerateAutoMedicalKnowledge: mocks.regenerate,
}));

const overview: AutoMedicalKnowledgeOverview = {
  settings: { enabled: true, display_mode: 'REVIEWED_ONLY', auto_visible_default: false },
  provider_cooldown: null,
  jobs: [{
    id: 4, topic_id: 2, disease_group_id: '5', factor_type: 'WEATHER',
    factor_key: 'precipitation', factor_value: null, status: 'FAILED', attempt_count: 1,
    trigger_type: 'PARENT', created_at: '2026-08-28T09:00:00', started_at: null,
    finished_at: null, next_retry_at: null, last_error_code: 'LLM_INVALID_RESPONSE',
    is_current_attempt: true, legacy: false,
    pipeline_version: 'auto_medical_knowledge_v1_compat',
    history: [],
    diagnostics: {
      attempt: 1, queries_run: 2, raw_results: 18, deduplicated: 14,
      disease_relevant: 7, factor_relevant: 4, pediatric_relevant: 3,
      usable_evidence: 3, selected_for_generation: 3, insufficient_reason: null,
      queries: ['("Influenza"[Title/Abstract]) AND ("humidity"[Title/Abstract])'],
      sources: [{
        pmid: '123', title: 'Relevant source title', decision: 'SELECTED',
        reason_code: 'SELECTED_FOR_GENERATION', stage: 'STRICT',
      }],
      pipeline_version: 'auto_medical_knowledge_v1_compat', failure: null,
    },
  }],
  revisions: [{
    id: 8, topic_id: 2, disease_group_id: '5', factor_type: 'WEATHER',
    factor_key: 'precipitation', factor_value: null, weather_factor: 'precipitation',
    revision_number: 1, generation_status: 'READY', evidence_level: 'SUPPORTED',
    generation_mode: 'AI_FULL', fallback_reason_code: null,
    evidence_scope: 'PARTIAL_GROUP', short_explanation_vi: 'Giải thích tự động.',
    detailed_explanation_vi: 'Chi tiết.', limitations_vi: 'Giới hạn.', is_visible: false,
    llm_model: 'model', prompt_version: 'auto-v1', generated_at: '2026-08-28T09:00:00',
    source_retrieved_at: '2026-08-28T08:00:00', sources: [{
      source_id: 3, title: 'Pediatric PubMed evidence', journal: 'Journal',
      publication_year: 2025, pmid: '40123456', doi: null,
      url: 'https://pubmed.ncbi.nlm.nih.gov/40123456/', trust_class: 'PUBMED',
      content_kind: 'ABSTRACT', source_role: 'PRIMARY', relevance_note: 'DIRECT: phù hợp',
      population_relevance: 'PEDIATRIC_DIRECT', population_note: 'Trẻ em.',
    }],
    diagnostics: null,
  }],
};

const offOverview: AutoMedicalKnowledgeOverview = {
  ...overview,
  settings: { ...overview.settings, enabled: false },
};

const insufficientOverview: AutoMedicalKnowledgeOverview = {
  ...overview,
  jobs: [{
    ...overview.jobs[0], status: 'INSUFFICIENT', last_error_code: null,
    diagnostics: {
      ...overview.jobs[0].diagnostics!, selected_for_generation: 0,
      insufficient_reason: 'NO_FACTOR_RELEVANT_SOURCE',
    },
  }],
  revisions: [{
    ...overview.revisions[0], generation_status: 'INSUFFICIENT', evidence_level: 'INSUFFICIENT',
    short_explanation_vi: null, detailed_explanation_vi: null, is_visible: false, sources: [],
    diagnostics: {
      ...overview.jobs[0].diagnostics!, selected_for_generation: 0,
      insufficient_reason: 'NO_FACTOR_RELEVANT_SOURCE',
    },
  }],
};

function overviewWithStatus(
  status: AutoMedicalKnowledgeOverview['jobs'][number]['status'],
  enabled = true,
): AutoMedicalKnowledgeOverview {
  return {
    ...overview,
    settings: { ...overview.settings, enabled },
    jobs: [{
      ...overview.jobs[0],
      status,
      last_error_code: status === 'FAILED' ? 'LLM_INVALID_RESPONSE' : null,
    }],
  };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AutoMedicalKnowledgePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.overview.mockResolvedValue(overview);
    mocks.settings.mockResolvedValue(overview.settings);
    mocks.visibility.mockResolvedValue({ ok: true, revision_id: 8, message: 'ok' });
    mocks.retry.mockResolvedValue({ ok: true, job_id: 4, message: 'ok' });
    mocks.regenerate.mockResolvedValue({ ok: true, job_id: 5, message: 'ok' });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('does not poll while every current job is terminal', async () => {
    vi.useFakeTimers();
    render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();

    await act(async () => { await vi.advanceTimersByTimeAsync(12_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(1);
  });

  it.each(['READY', 'FAILED'] as const)(
    'polls a queued job until it becomes %s and then stops',
    async (terminalStatus) => {
      vi.useFakeTimers();
      mocks.overview
        .mockResolvedValueOnce(overviewWithStatus('QUEUED'))
        .mockResolvedValueOnce(overviewWithStatus(terminalStatus));
      render(<AutoMedicalKnowledgePanel canManage />);
      await flushPromises();
      const initialJobRow = screen.getByText('5 · precipitation').parentElement!;
      expect(within(initialJobRow).getByText('Đang chờ')).toBeVisible();

      await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
      expect(mocks.overview).toHaveBeenCalledTimes(2);
      const updatedJobRow = screen.getByText('5 · precipitation').parentElement!;
      expect(within(updatedJobRow).getByText(
        terminalStatus === 'READY' ? 'Hoàn thành' : 'Lỗi',
      )).toBeVisible();
      await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
      expect(mocks.overview).toHaveBeenCalledTimes(2);
    },
  );

  it('starts polling after retry returns a newly queued state', async () => {
    vi.useFakeTimers();
    mocks.overview
      .mockResolvedValueOnce(overview)
      .mockResolvedValueOnce(overviewWithStatus('QUEUED'))
      .mockResolvedValueOnce(overviewWithStatus('READY'));
    render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();

    fireEvent.click(screen.getByRole('button', { name: /Thử lại/i }));
    await flushPromises();
    expect(mocks.retry).toHaveBeenCalledWith(4);
    expect(mocks.overview).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(3);
  });

  it('cleans up polling on unmount', async () => {
    vi.useFakeTimers();
    mocks.overview.mockResolvedValue(overviewWithStatus('GENERATING'));
    const view = render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();
    view.unmount();

    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(1);
  });

  it('does not create duplicate intervals after rerender or overlap background requests', async () => {
    vi.useFakeTimers();
    let resolvePoll!: (value: AutoMedicalKnowledgeOverview) => void;
    mocks.overview
      .mockResolvedValueOnce(overviewWithStatus('SEARCHING'))
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePoll = resolve; }));
    const view = render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();
    view.rerender(<AutoMedicalKnowledgePanel canManage />);

    await act(async () => { await vi.advanceTimersByTimeAsync(12_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(2);
    resolvePoll(overviewWithStatus('READY'));
    await flushPromises();
  });

  it('preserves the last confirmed queued state when a background poll fails', async () => {
    vi.useFakeTimers();
    mocks.overview
      .mockResolvedValueOnce(overviewWithStatus('QUEUED'))
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce(overviewWithStatus('READY'));
    render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();

    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    await flushPromises();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mocks.overview).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(3);
  });

  it('does not poll active-looking jobs while the persisted service state is OFF', async () => {
    vi.useFakeTimers();
    mocks.overview.mockResolvedValue(overviewWithStatus('QUEUED', false));
    render(<AutoMedicalKnowledgePanel canManage />);
    await flushPromises();

    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(mocks.overview).toHaveBeenCalledTimes(1);
  });

  it('labels Auto content as unreviewed and exposes provenance and queue state', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/chưa được kiểm duyệt y khoa/i)).toBeVisible();
    expect(screen.getAllByText('Lỗi')).not.toHaveLength(0);
    expect(screen.getByText(/Lỗi lịch sử cũ — phiên bản này chưa lưu đủ chi tiết/)).toBeVisible();
    expect(screen.getByText(/Pediatric PubMed evidence/)).toBeVisible();
    expect(screen.getByText(/PMID 40123456/)).toBeVisible();
    expect(screen.getByText(/Chế độ tạo: AI đầy đủ/)).toBeVisible();
  });

  it('labels deterministic safe fallback without exposing technical reason codes', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      revisions: [{
        ...overview.revisions[0],
        generation_mode: 'SAFE_FALLBACK',
        fallback_reason_code: 'REPAIR_PROVIDER_FAILURE',
      }],
    });
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/Chế độ tạo: Bản rút gọn an toàn/)).toBeVisible();
    expect(screen.getByText(/không vượt qua kiểm tra hợp đồng đầu ra/)).toBeVisible();
    expect(container).not.toHaveTextContent('REPAIR_PROVIDER_FAILURE');
  });

  it('shows transparent bounded discovery diagnostics without raw evidence', async () => {
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Chi tiết tìm kiếm')).toBeVisible();
    fireEvent.click(screen.getByText('Chi tiết tìm kiếm'));
    expect(screen.getByText('Kết quả PubMed').parentElement).toHaveTextContent('18');
    expect(screen.getByText('Sau loại trùng').parentElement).toHaveTextContent('14');
    expect(screen.getByText(/"Influenza"\[Title\/Abstract\]/)).toBeVisible();
    expect(screen.getByText(/Relevant source title/)).toBeVisible();
    expect(container).toHaveTextContent('không hiển thị nội dung bằng chứng');
    expect(container).not.toHaveTextContent('full raw abstract body');
  });

  it('explains insufficient evidence precisely and allows explicit regeneration', async () => {
    mocks.overview.mockResolvedValue(insufficientOverview);
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findAllByText('Không đủ bằng chứng')).not.toHaveLength(0);
    expect(screen.getAllByText('Chưa tìm được bài đánh giá trực tiếp yếu tố đã chọn.')).not.toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Tạo lại' }));
    await waitFor(() => expect(mocks.regenerate).toHaveBeenCalled());
  });

  it('fails closed when persisted runtime state cannot be loaded', async () => {
    mocks.overview.mockRejectedValue(new Error('settings unavailable'));
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Không xác định được trạng thái dịch vụ Auto Medical Knowledge.',
    );
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('keeps staff view read-only', async () => {
    render(<AutoMedicalKnowledgePanel canManage={false} />);
    await screen.findByText('Auto Medical Knowledge');
    expect(screen.queryByRole('button', { name: 'Cho phép hiển thị' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Thử lại' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Chế độ hiển thị Auto/)).toBeDisabled();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.getByText(/Auto đang hoạt động/)).toBeVisible();
  });

  it('renders persisted OFF state and lets Admin enable without restart', async () => {
    mocks.overview
      .mockResolvedValueOnce(offOverview)
      .mockResolvedValue({ ...offOverview, settings: { ...offOverview.settings, enabled: true } });
    mocks.settings.mockResolvedValue({ ...offOverview.settings, enabled: true });
    render(<AutoMedicalKnowledgePanel canManage />);

    expect(await screen.findByText('Đang tắt')).toBeVisible();
    expect(screen.getByText(/Nội dung và lịch sử đã có vẫn được giữ nguyên/)).toBeVisible();
    const toggle = screen.getByRole('switch', { name: /Bật hoặc tắt Auto/ });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(toggle);

    await waitFor(() => expect(mocks.settings).toHaveBeenCalledWith({ enabled: true }));
    expect(screen.getByText('Đang bật')).toBeVisible();
    expect(screen.getByText(/Auto đang hoạt động/)).toBeVisible();
  });

  it('retains confirmed state and shows a focused error when toggle fails', async () => {
    mocks.overview.mockResolvedValue(offOverview);
    mocks.settings.mockRejectedValue(new Error('network'));
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByRole('switch'));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Không thể thay đổi trạng thái Auto Medical Knowledge.',
    );
    expect(screen.getByText('Đang tắt')).toBeVisible();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('shows loading and prevents repeated toggle requests', async () => {
    mocks.overview
      .mockResolvedValueOnce(offOverview)
      .mockResolvedValue({ ...offOverview, settings: { ...offOverview.settings, enabled: true } });
    let resolveSettings!: (value: typeof overview.settings) => void;
    mocks.settings.mockImplementation(() => new Promise((resolve) => {
      resolveSettings = resolve;
    }));
    render(<AutoMedicalKnowledgePanel canManage />);
    const toggle = await screen.findByRole('switch');
    fireEvent.click(toggle);

    expect(await screen.findByText('Đang bật…')).toBeDisabled();
    fireEvent.click(toggle);
    expect(mocks.settings).toHaveBeenCalledTimes(1);
    resolveSettings({ ...offOverview.settings, enabled: true });
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'));
  });

  it('refreshes from persisted backend state without exposing configuration values', async () => {
    mocks.overview
      .mockResolvedValueOnce(offOverview)
      .mockResolvedValueOnce({ ...offOverview, settings: { ...offOverview.settings, enabled: true } });
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText('Đang tắt')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Làm mới' }));
    await waitFor(() => expect(screen.getByText('Đang bật')).toBeVisible());
    expect(container).not.toHaveTextContent(/API_KEY|SECRET_KEY|\.env/);
  });

  it('allows admin visibility without calling it approval', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Cho phép hiển thị' }));
    await waitFor(() => expect(mocks.visibility).toHaveBeenCalledWith(8, true));
    expect(screen.getByText(/không phải là phê duyệt y khoa/i)).toBeVisible();
  });

  it('supports explicit retry and fallback setting changes', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Thử lại' }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith(4));
    fireEvent.change(screen.getByLabelText(/Chế độ hiển thị Auto/), {
      target: { value: 'REVIEWED_WITH_AUTO_FALLBACK' },
    });
    await waitFor(() => expect(mocks.settings).toHaveBeenCalledWith({
      display_mode: 'REVIEWED_WITH_AUTO_FALLBACK',
    }));
  });

  it('shows precise safe validator diagnostics without raw output or evidence', async () => {
    const failureOverview: AutoMedicalKnowledgeOverview = {
      ...overview,
      jobs: [{
        ...overview.jobs[0],
        last_error_code: 'AUTO_OUTPUT_UNSUPPORTED_MECHANISM',
        diagnostics: {
          ...overview.jobs[0].diagnostics!,
          failure: {
            code: 'AUTO_OUTPUT_UNSUPPORTED_MECHANISM',
            field: 'detailed_explanation_vi', source_id: null, numeric_value: null,
            safe_detail: 'Generated text contains a mechanism absent from selected evidence.',
            provider_error_class: 'AutoOutputSafetyError',
          },
        },
      }],
    };
    mocks.overview.mockResolvedValue(failureOverview);
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByText('Chi tiết kiểm tra'));
    expect(screen.getByText('AUTO_OUTPUT_UNSUPPORTED_MECHANISM')).toBeVisible();
    expect(screen.getByText('detailed_explanation_vi')).toBeVisible();
    expect(container).not.toHaveTextContent('raw provider output');
    expect(container).not.toHaveTextContent('full raw abstract body');
    expect(screen.getAllByRole('button', { name: 'Tạo lại' })[0]).toBeEnabled();
  });

  it('shows safe initial-versus-repair provider diagnostics', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{
        ...overview.jobs[0],
        last_error_code: 'AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED',
        diagnostics: {
          ...overview.jobs[0].diagnostics!,
          failure: {
            code: 'AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED',
            field: null, source_id: null, numeric_value: null,
            safe_detail: 'Groq rejected the structured-output request.',
            provider_error_class: 'DraftGeneratorProviderRequestRejectedError',
            provider: 'groq', http_status: 400,
            call_purpose: 'CONTRACT_REPAIR', generation_call_number: 2,
            max_generation_calls: 2, provider_error_category: 'json_validate_failed',
          },
        },
      }],
    });
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    const details = await screen.findByText(/Chi ti.*ki.*m tra/);
    fireEvent.click(details);
    expect(screen.getByText('Sửa cấu trúc nội dung')).toBeVisible();
    expect(screen.getByText(/2 \/ 2/)).toBeVisible();
    expect(screen.getByText('400')).toBeVisible();
    expect(screen.getByText('GROQ')).toBeVisible();
    expect(screen.getByText('json_validate_failed')).toBeVisible();
    expect(container).not.toHaveTextContent('failed_generation');
    expect(container).not.toHaveTextContent('raw provider response');
  });

  it.each([
    ['AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED', 'không khai báo nguồn hỗ trợ'],
    ['AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID', 'không thuộc bộ bằng chứng đã chọn'],
    ['AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH', 'Không tìm thấy bằng chứng hỗ trợ số liệu'],
    ['AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID', 'Loại số liệu AI khai báo không phù hợp'],
    ['AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH', 'Loại số liệu AI khai báo khác với ý nghĩa'],
  ])('shows a safe V2 numeric-contract reason for %s', async (code, message) => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{ ...overview.jobs[0], last_error_code: code }],
    });
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(new RegExp(message, 'i'))).toBeVisible();
  });

  it.each([
    ['AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED', 'từ chối yêu cầu tạo dữ liệu'],
    ['AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY', 'không trả về nội dung có cấu trúc'],
    ['AUTO_OUTPUT_PROVIDER_INCOMPLETE', 'chưa hoàn tất nội dung có cấu trúc'],
  ])('shows a safe provider-boundary reason for %s', async (code, message) => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{ ...overview.jobs[0], last_error_code: code }],
    });
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(new RegExp(message, 'i'))).toBeVisible();
  });

  it('shows structural and rate-limit messages with appropriate retry state', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{ ...overview.jobs[0], last_error_code: 'AUTO_OUTPUT_SCHEMA_INVALID' }],
    });
    const { rerender } = render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/không đúng lược đồ/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeEnabled();

    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{
        ...overview.jobs[0], last_error_code: 'LLM_RATE_LIMITED',
        next_retry_at: '2026-08-28T10:00:00',
      }],
    });
    rerender(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(screen.getByRole('button', { name: 'Làm mới' }));
    expect(await screen.findByText(/giới hạn lượt gọi/)).toBeVisible();
    expect(screen.getByText(/Tiếp tục sau/)).toBeVisible();
  });

  it('labels generic historical errors without guessing a new failure reason', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{ ...overview.jobs[0], legacy: true, pipeline_version: null }],
    });
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/Lỗi lịch sử cũ — phiên bản này chưa lưu đủ chi tiết/)).toBeVisible();
    expect(screen.getByText(/dữ liệu chẩn đoán chi tiết chưa được ghi/)).toBeVisible();
  });

  it('shows unsupported-number field and value without exposing raw output', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      jobs: [{
        ...overview.jobs[0],
        last_error_code: 'AUTO_OUTPUT_UNSUPPORTED_NUMBER',
        diagnostics: {
          ...overview.jobs[0].diagnostics!,
          failure: {
            code: 'AUTO_OUTPUT_UNSUPPORTED_NUMBER',
            field: 'detailed_explanation_vi', source_id: null, numeric_value: '5.087',
            safe_detail: 'Safe deterministic numeric rejection.',
            provider_error_class: 'AutoOutputSafetyError',
          },
        },
      }],
    });
    const { container } = render(<AutoMedicalKnowledgePanel canManage />);
    fireEvent.click(await screen.findByText('Chi tiết kiểm tra'));
    expect(screen.getAllByText(/số liệu không tìm thấy/)).not.toHaveLength(0);
    expect(screen.getByText('detailed_explanation_vi')).toBeVisible();
    expect(screen.getByText('5.087')).toBeVisible();
    expect(container).not.toHaveTextContent('raw provider output');
  });

  it('shows persisted provider cooldown and disables retry until it expires', async () => {
    mocks.overview.mockResolvedValue({
      ...overview,
      provider_cooldown: {
        provider: 'GROQ', active: true,
        cooldown_until: '2099-08-30T12:00:00',
        reason: 'LLM_RATE_LIMITED', updated_at: '2099-08-30T11:55:00',
      },
      jobs: [{
        ...overview.jobs[0], last_error_code: 'LLM_RATE_LIMITED',
        next_retry_at: '2099-08-30T12:00:00',
      }],
    });
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findByText(/GROQ đang tạm nghỉ/)).toBeVisible();
    expect(screen.getByText(/Nút thử lại tạm khóa/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeDisabled();
  });

  it('keeps latest READY primary and legacy failure collapsed', async () => {
    const current = {
      ...overview.jobs[0], id: 5, status: 'READY' as const, last_error_code: null,
      is_current_attempt: true, legacy: false,
    };
    const legacy = {
      ...overview.jobs[0], id: 4, is_current_attempt: false, legacy: true,
      pipeline_version: null, diagnostics: null,
    };
    mocks.overview.mockResolvedValue({ ...overview, jobs: [current, legacy] });
    render(<AutoMedicalKnowledgePanel canManage />);
    expect(await screen.findAllByText('Hoàn thành')).not.toHaveLength(0);
    expect(screen.queryByText(/Lịch sử cũ — dữ liệu chẩn đoán/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Hiện lịch sử cũ'));
    fireEvent.click(screen.getByText('Lịch sử 1 lần'));
    expect(screen.getByText(/Lịch sử cũ — dữ liệu chẩn đoán/)).toBeVisible();
    expect(screen.getByText('Lịch sử — Lỗi')).toBeVisible();
  });

  it('filters current topics and prevents duplicate retry clicks', async () => {
    let resolveRetry!: (value: unknown) => void;
    mocks.retry.mockImplementation(() => new Promise((resolve) => { resolveRetry = resolve; }));
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Trạng thái hiện tại theo chủ đề');
    fireEvent.click(screen.getByRole('button', { name: 'Hoàn thành' }));
    expect(screen.getByText('Không có kết quả phù hợp bộ lọc.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Lỗi' }));
    const retry = screen.getByRole('button', { name: 'Thử lại' });
    fireEvent.click(retry); fireEvent.click(retry);
    expect(mocks.retry).toHaveBeenCalledTimes(1);
    resolveRetry({ ok: true });
    await waitFor(() => expect(mocks.overview).toHaveBeenCalledTimes(2));
  });

  it('filters the Auto dashboard by search, generation mode, and factor without refetching', async () => {
    render(<AutoMedicalKnowledgePanel canManage />);
    await screen.findByText('Trạng thái hiện tại theo chủ đề');
    const callsAfterLoad = mocks.overview.mock.calls.length;

    fireEvent.change(screen.getByLabelText('Tìm chủ đề Auto'), { target: { value: 'không tồn tại' } });
    expect(screen.getByText('Không có kết quả phù hợp bộ lọc.')).toBeVisible();
    fireEvent.change(screen.getByLabelText('Tìm chủ đề Auto'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Lọc chế độ tạo'), { target: { value: 'AI_FULL' } });
    fireEvent.change(screen.getByLabelText('Lọc yếu tố Auto'), { target: { value: 'WEATHER|precipitation|' } });

    expect(mocks.overview).toHaveBeenCalledTimes(callsAfterLoad);
  });
});
