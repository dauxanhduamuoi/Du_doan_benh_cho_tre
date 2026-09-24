import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import ServiceConfigurationPanel from './ServiceConfigurationPanel';

const mocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  testPubmed: vi.fn(),
  testLlm: vi.fn(),
  getProviderSettings: vi.fn(),
  updateProviderSetting: vi.fn(),
}));

vi.mock('@/lib/medicalKnowledgeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/medicalKnowledgeApi')>();
  return {
    ...actual,
    getMedicalKnowledgeServiceStatus: mocks.getStatus,
    testPubMedConnection: mocks.testPubmed,
    testLlmConnection: mocks.testLlm,
    getMedicalEvidenceProviderSettings: mocks.getProviderSettings,
    updateMedicalEvidenceProviderSetting: mocks.updateProviderSetting,
  };
});

const configured = {
  pubmed: { configured: true, email_configured: true, api_key_configured: true },
  llm: {
    configured: true,
    provider: 'openai',
    model: 'account-enabled-model',
    api_key_configured: true,
    mode: 'remote' as const,
    local: false,
  },
};

describe('ServiceConfigurationPanel', () => {
  beforeEach(() => {
    mocks.getStatus.mockReset().mockResolvedValue(configured);
    mocks.testPubmed.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối PubMed thành công.' });
    mocks.testLlm.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối OpenAI thành công.' });
    const providers = [
      { provider_id: 'PUBMED', display_name: 'PubMed', description: 'Research', workflow: 'AUTO', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
      { provider_id: 'PUBMED', display_name: 'PubMed', description: 'Research', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
      { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', description: 'Official', workflow: 'AUTO', enabled: false, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
      { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', description: 'Official', workflow: 'REVIEWED', enabled: false, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
    ];
    mocks.getProviderSettings.mockReset().mockResolvedValue({ providers });
    mocks.updateProviderSetting.mockReset().mockImplementation(async (payload: { provider_id: string; workflow: string; enabled: boolean }) => ({ providers: providers.map((item) => item.provider_id === payload.provider_id && item.workflow === payload.workflow ? { ...item, enabled: payload.enabled } : item) }));
  });

  it('renders the compact service configuration panel', async () => {
    render(<ServiceConfigurationPanel />);
    expect(screen.getByRole('heading', { name: 'Cấu hình dịch vụ' })).toBeInTheDocument();
    expect(await screen.findByRole('article', { name: 'PubMed' })).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'OpenAI' })).toBeInTheDocument();
  });

  it('renders configured PubMed and optional API key state', async () => {
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'PubMed' });
    expect(within(section).getByText('Đã cấu hình')).toBeInTheDocument();
    expect(within(section).getAllByText('Đã thiết lập')).toHaveLength(2);
  });

  it('renders missing PubMed configuration without exposing email', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      pubmed: { configured: false, email_configured: false, api_key_configured: false },
    });
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'PubMed' });
    expect(within(section).getByText('Chưa cấu hình')).toBeInTheDocument();
    expect(screen.getByText('PubMed: NCBI_EMAIL')).toBeInTheDocument();
    expect(screen.queryByText(/private@example/i)).not.toBeInTheDocument();
  });

  it('renders configured OpenAI state and the exact model identifier', async () => {
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'OpenAI' });
    expect(within(section).getByText('account-enabled-model')).toBeInTheDocument();
    expect(within(section).getAllByText('Đã thiết lập').length).toBeGreaterThan(0);
  });

  it('renders Ollama as local AI without an API key row', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'ollama',
        model: 'qwen3:8b',
        api_key_configured: false,
        mode: 'local',
        local: true,
      },
    });
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'AI cục bộ' });
    expect(within(section).getByText('Ollama')).toBeInTheDocument();
    expect(within(section).getByText('qwen3:8b')).toBeInTheDocument();
    expect(within(section).queryByText('API key')).not.toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Kiểm tra AI cục bộ' })).toBeInTheDocument();
    expect(within(section).getByRole('heading', { name: 'AI tạo bản nháp' })).toBeInTheDocument();
    expect(within(section).getByText(/không sử dụng OpenAI API cho provider hiện tại/i)).toBeInTheDocument();
  });

  it('shows the Ollama model configuration requirement', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: false,
        provider: 'ollama',
        model: null,
        api_key_configured: false,
        mode: 'local',
        local: true,
      },
    });
    render(<ServiceConfigurationPanel />);
    await screen.findByRole('article', { name: 'AI cục bộ' });
    expect(screen.getByText('Ollama: OLLAMA_MODEL')).toBeInTheDocument();
    expect(screen.queryByText('OpenAI: OPENAI_API_KEY và OPENAI_MODEL')).not.toBeInTheDocument();
  });

  it('shows a specific safe local-model failure', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'ollama',
        model: 'qwen3:8b',
        api_key_configured: false,
        mode: 'local',
        local: true,
      },
    });
    mocks.testLlm.mockRejectedValue(
      new ApiError(503, 'Model AI cục bộ chưa được cài đặt trong Ollama.'),
    );
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'AI cục bộ' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra AI cục bộ' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent(
      'Model AI cục bộ chưa được cài đặt trong Ollama.',
    );
  });

  it('shows local AI loading and success only after an explicit click', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'ollama',
        model: 'qwen3:8b',
        api_key_configured: false,
        mode: 'local',
        local: true,
      },
    });
    let resolveTest: (value: { ok: boolean; message: string }) => void = () => undefined;
    mocks.testLlm.mockReturnValue(new Promise((resolve) => { resolveTest = resolve; }));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'AI cục bộ' });
    expect(mocks.testLlm).not.toHaveBeenCalled();
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra AI cục bộ' }));
    expect(within(section).getByRole('button', { name: 'Đang kiểm tra…' })).toBeDisabled();
    resolveTest({ ok: true, message: 'Kết nối AI cục bộ Ollama thành công.' });
    expect(await within(section).findByRole('status')).toHaveTextContent(
      'Kết nối AI cục bộ Ollama thành công.',
    );
  });

  it('shows a safe Ollama-not-running message', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'ollama',
        model: 'qwen3:8b',
        api_key_configured: false,
        mode: 'local',
        local: true,
      },
    });
    mocks.testLlm.mockRejectedValue(
      new ApiError(
        502,
        'Không kết nối được AI cục bộ Ollama. Hãy mở Ollama trên máy và thử lại.',
      ),
    );
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'AI cục bộ' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra AI cục bộ' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent(
      'Không kết nối được AI cục bộ Ollama.',
    );
  });

  it('renders Groq as an online API with model, boolean key state, and privacy note', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        api_key_configured: true,
        mode: 'cloud_api',
        local: false,
      },
    });
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'Groq' });
    expect(within(section).getByText('API trực tuyến')).toBeInTheDocument();
    expect(within(section).getByText('Groq')).toBeInTheDocument();
    expect(within(section).getByText('openai/gpt-oss-20b')).toBeInTheDocument();
    expect(within(section).getAllByText('Đã thiết lập')).toHaveLength(1);
    expect(within(section).getByText(/Groq chạy AI trên máy chủ bên ngoài/i)).toBeInTheDocument();
    expect(within(section).getByText(/Không gửi dữ liệu bệnh nhi/i)).toBeInTheDocument();
    expect(within(section).getByText(/phụ thuộc giới hạn\/gói của tài khoản Groq/i)).toBeInTheDocument();
    expect(within(section).getByText(/không tự chuyển sang nhà cung cấp khác/i)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('gsk_private_secret');
  });

  it('renders missing Groq configuration without exposing a key value', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: false,
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        api_key_configured: false,
        mode: 'cloud_api',
        local: false,
      },
    });
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'Groq' });
    expect(within(section).getByText('Chưa cấu hình')).toBeInTheDocument();
    expect(screen.getByText('Groq: GROQ_API_KEY và GROQ_MODEL')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('gsk_private_secret');
  });

  it('runs the Groq connection test only after a click and shows loading and success', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        api_key_configured: true,
        mode: 'cloud_api',
        local: false,
      },
    });
    let resolveTest: (value: { ok: boolean; message: string }) => void = () => undefined;
    mocks.testLlm.mockReturnValue(new Promise((resolve) => { resolveTest = resolve; }));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'Groq' });
    expect(mocks.testLlm).not.toHaveBeenCalled();
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(within(section).getByRole('button', { name: 'Đang kiểm tra…' })).toBeDisabled();
    resolveTest({ ok: true, message: 'Kết nối Groq thành công.' });
    expect(await within(section).findByRole('status')).toHaveTextContent('Kết nối Groq thành công.');
  });

  it('shows the safe Groq rate-limit message', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        api_key_configured: true,
        mode: 'cloud_api',
        local: false,
      },
    });
    mocks.testLlm.mockRejectedValue(
      new ApiError(429, 'Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau.'),
    );
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'Groq' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent(
      'Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau.',
    );
  });

  it('shows the safe Groq authentication message without raw provider detail', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: {
        configured: true,
        provider: 'groq',
        model: 'openai/gpt-oss-20b',
        api_key_configured: true,
        mode: 'cloud_api',
        local: false,
      },
    });
    mocks.testLlm.mockRejectedValue(new ApiError(502, 'Không thể xác thực với Groq.'));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'Groq' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent(
      'Không thể xác thực với Groq.',
    );
    expect(document.body).not.toHaveTextContent('raw provider response');
  });

  it('renders missing OpenAI configuration and required variable names', async () => {
    mocks.getStatus.mockResolvedValue({
      ...configured,
      llm: { configured: false, provider: 'openai', model: null, api_key_configured: false, mode: 'remote', local: false },
    });
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'OpenAI' });
    expect(within(section).getByText('Chưa cấu hình')).toBeInTheDocument();
    expect(screen.getByText('OpenAI: OPENAI_API_KEY và OPENAI_MODEL')).toBeInTheDocument();
  });

  it('never renders API key or NCBI email values', async () => {
    render(<ServiceConfigurationPanel />);
    await screen.findByRole('article', { name: 'OpenAI' });
    expect(document.body).not.toHaveTextContent('sk-fixture-secret');
    expect(document.body).not.toHaveTextContent('private@example.invalid');
  });

  it('does not auto-call either connection test on page load', async () => {
    render(<ServiceConfigurationPanel />);
    await screen.findByRole('article', { name: 'OpenAI' });
    expect(mocks.testPubmed).not.toHaveBeenCalled();
    expect(mocks.testLlm).not.toHaveBeenCalled();
  });

  it('shows PubMed loading and success states after an explicit click', async () => {
    let resolveTest: (value: { ok: boolean; message: string }) => void = () => undefined;
    mocks.testPubmed.mockReturnValue(new Promise((resolve) => { resolveTest = resolve; }));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'PubMed' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(within(section).getByRole('button', { name: 'Đang kiểm tra…' })).toBeDisabled();
    resolveTest({ ok: true, message: 'Kết nối PubMed thành công.' });
    expect(await within(section).findByRole('status')).toHaveTextContent('Kết nối PubMed thành công.');
  });

  it('shows a safe PubMed failure state', async () => {
    mocks.testPubmed.mockRejectedValue(new ApiError(502, 'raw provider response'));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'PubMed' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent('Hiện không thể kết nối PubMed');
    expect(document.body).not.toHaveTextContent('raw provider response');
  });

  it('shows OpenAI loading, cost notice, and success after an explicit click', async () => {
    let resolveTest: (value: { ok: boolean; message: string }) => void = () => undefined;
    mocks.testLlm.mockReturnValue(new Promise((resolve) => { resolveTest = resolve; }));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'OpenAI' });
    expect(within(section).getByText('Kiểm tra OpenAI sẽ gửi một yêu cầu rất nhỏ tới API.')).toBeInTheDocument();
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(within(section).getByRole('button', { name: 'Đang kiểm tra…' })).toBeDisabled();
    resolveTest({ ok: true, message: 'Kết nối OpenAI thành công.' });
    expect(await within(section).findByRole('status')).toHaveTextContent('Kết nối OpenAI thành công.');
  });

  it('shows a safe OpenAI failure state', async () => {
    mocks.testLlm.mockRejectedValue(new ApiError(503, 'private model error'));
    render(<ServiceConfigurationPanel />);
    const section = await screen.findByRole('article', { name: 'OpenAI' });
    fireEvent.click(within(section).getByRole('button', { name: 'Kiểm tra kết nối' }));
    expect(await within(section).findByRole('alert')).toHaveTextContent('OpenAI chưa được cấu hình đầy đủ.');
    expect(document.body).not.toHaveTextContent('private model error');
  });

  it('shows the canonical relative .env path and restart instruction', async () => {
    render(<ServiceConfigurationPanel />);
    await waitFor(() => expect(mocks.getStatus).toHaveBeenCalledTimes(1));
    expect(screen.getByText('seasonal_disease_backend/.env')).toBeInTheDocument();
    expect(screen.getByText(/hãy khởi động lại backend để cấu hình mới có hiệu lực/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[A-Z]:\\/i);
  });

  it('renders both provider workflows from the API without a provider-count branch', async () => {
    render(<ServiceConfigurationPanel showProviderSettings canManageProviders />);
    expect(await screen.findByRole('article', { name: 'World Health Organization (WHO)' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'World Health Organization (WHO) AUTO' })).not.toBeChecked();
    expect(screen.getByRole('switch', { name: 'World Health Organization (WHO) REVIEWED' })).not.toBeChecked();
  });

  it('admin toggle updates one exact provider workflow', async () => {
    render(<ServiceConfigurationPanel showProviderSettings canManageProviders />);
    fireEvent.click(await screen.findByRole('switch', { name: 'World Health Organization (WHO) AUTO' }));
    await waitFor(() => expect(mocks.updateProviderSetting).toHaveBeenCalledWith({ provider_id: 'WHO', workflow: 'AUTO', enabled: true }));
    expect(screen.getByRole('switch', { name: 'World Health Organization (WHO) AUTO' })).toBeChecked();
    expect(screen.getByRole('switch', { name: 'World Health Organization (WHO) REVIEWED' })).not.toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent('đã được bật cho Tự động');
  });

  it('staff sees availability but cannot mutate provider settings', async () => {
    render(<ServiceConfigurationPanel showProviderSettings />);
    expect(await screen.findByRole('article', { name: 'World Health Organization (WHO)' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'PubMed AUTO' })).toBeDisabled();
    expect(screen.getByText('Chỉ admin có thể thay đổi')).toBeInTheDocument();
  });
});
