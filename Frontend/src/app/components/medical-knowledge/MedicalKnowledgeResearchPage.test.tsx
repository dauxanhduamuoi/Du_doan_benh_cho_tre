import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import type {
  DraftRevision,
  MedicalKnowledgeOptions,
  PubMedSearchResponse,
} from '@/lib/medicalKnowledgeApi';
import MedicalKnowledgeResearchPage from './MedicalKnowledgeResearchPage';

const mocks = vi.hoisted(() => ({
  role: 'admin',
  getOptions: vi.fn(),
  getServiceStatus: vi.fn(),
  testPubMedConnection: vi.fn(),
  testLlmConnection: vi.fn(),
  search: vi.fn(),
  importSources: vi.fn(),
  getHistory: vi.fn(),
  generateDraft: vi.fn(),
  getRevision: vi.fn(),
  updateDraft: vi.fn(),
}));

vi.mock('@/app/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, username: 'tester', role: mocks.role, permissions: [] } }),
}));

vi.mock('@/lib/medicalKnowledgeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/medicalKnowledgeApi')>();
  return {
    ...actual,
    getMedicalKnowledgeOptions: mocks.getOptions,
    getMedicalKnowledgeServiceStatus: mocks.getServiceStatus,
    testPubMedConnection: mocks.testPubMedConnection,
    testLlmConnection: mocks.testLlmConnection,
    searchPubMed: mocks.search,
    importPubMedSources: mocks.importSources,
    getMedicalKnowledgeDraftHistory: mocks.getHistory,
    generateMedicalKnowledgeDraft: mocks.generateDraft,
    getMedicalKnowledgeRevision: mocks.getRevision,
    updateMedicalKnowledgeDraft: mocks.updateDraft,
  };
});

const options: MedicalKnowledgeOptions = {
  disease_groups: [
    { id: '1', name: 'Tả - Cholera' },
    { id: '5', name: 'Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn' },
  ],
  weather_factors: [
    { value: 'temperature', label_vi: 'Nhiệt độ' },
    { value: 'humidity', label_vi: 'Độ ẩm' },
    { value: 'precipitation', label_vi: 'Mưa / lượng mưa' },
    { value: 'wind', label_vi: 'Gió' },
    { value: 'weather_condition', label_vi: 'Điều kiện thời tiết' },
  ],
  llm_draft_generation_available: true,
};

const longAbstract = 'Nghiên cứu quan sát mô tả mối liên hệ theo thời gian. '.repeat(10);
const searchResponse: PubMedSearchResponse = {
  disease_group_id: '5',
  weather_factor: 'precipitation',
  query: '("gastroenteritis"[Title/Abstract]) AND ("rainfall"[Title/Abstract])',
  count: 2,
  results: [
    {
      pmid: '12345678',
      title: 'Rainfall and pediatric gastroenteritis',
      authors: 'An Nguyen, BC Smith',
      journal: 'Journal of Pediatric Weather',
      publication_year: 2024,
      doi: '10.1000/rain',
      abstract_text: longAbstract,
      pubmed_url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
    },
    {
      pmid: '87654321',
      title: 'Record without abstract',
      authors: null,
      journal: null,
      publication_year: null,
      doi: null,
      abstract_text: null,
      pubmed_url: 'https://pubmed.ncbi.nlm.nih.gov/87654321/',
    },
  ],
};

const draftRevision: DraftRevision = {
  id: 21,
  topic_id: 7,
  revision_number: 2,
  status: 'DRAFT',
  evidence_level: 'LIMITED_OR_INDIRECT',
  evidence_scope: 'PARTIAL_GROUP',
  generated_by_llm: true,
  created_at: '2026-08-18T10:00:00',
  updated_at: '2026-08-18T10:00:00',
  disease_group_id: '5',
  disease_group_name: 'Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn',
  weather_factor: 'precipitation',
  short_explanation_vi: 'Mưa có liên hệ quan sát với một phần nhóm bệnh.',
  detailed_explanation_vi: 'Nghiên cứu ghi nhận mối liên hệ ở mức quần thể, chưa chứng minh nhân quả.',
  limitations_vi: 'Nguồn chỉ nghiên cứu một subtype và không dự đoán nguy cơ cá nhân.',
  parent_display_allowed: false,
  llm_model: 'configured-model',
  prompt_version: 'medical_knowledge_v1',
  created_by: 1,
  reviewed_by: null,
  reviewed_at: null,
  sources: [
    {
      id: 10,
      source_type: 'PUBMED',
      pmid: '12345678',
      doi: '10.1000/rain',
      title: 'Rainfall and pediatric gastroenteritis',
      authors: 'An Nguyen',
      journal: 'Journal of Pediatric Weather',
      publication_year: 2024,
      abstract_text: longAbstract,
      url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
      source_role: 'PRIMARY',
      sort_order: 0,
      relevance_note: 'DIRECT: Nghiên cứu trực tiếp yếu tố mưa.',
    },
  ],
};

async function renderReadyPage(role = 'admin') {
  mocks.role = role;
  render(<MedicalKnowledgeResearchPage />);
  await screen.findByRole('option', { name: '5 — Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn' });
}

async function chooseContext() {
  fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '5' } });
  fireEvent.change(screen.getByLabelText('2. Yếu tố thời tiết'), { target: { value: 'precipitation' } });
  await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('5', 'precipitation'));
}

function addTerm(term = 'gastroenteritis') {
  const input = screen.getByLabelText('3. Từ khóa bệnh dùng để tìm PubMed');
  fireEvent.change(input, { target: { value: term } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
}

async function runSuccessfulSearch() {
  await renderReadyPage();
  await chooseContext();
  addTerm();
  fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
  await screen.findByText('Tìm thấy 2 tài liệu');
}

async function importAllSources() {
  await runSuccessfulSearch();
  fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả kết quả' }));
  fireEvent.click(screen.getByRole('button', { name: 'Thêm 2 tài liệu vào kho nguồn' }));
  await screen.findByRole('button', { name: 'Tạo bản nháp bằng AI' });
}

describe('MedicalKnowledgeResearchPage', () => {
  beforeEach(() => {
    mocks.role = 'admin';
    mocks.getOptions.mockReset().mockResolvedValue(options);
    mocks.getServiceStatus.mockReset().mockResolvedValue({
      pubmed: { configured: true, email_configured: true, api_key_configured: false },
      llm: { configured: true, provider: 'openai', model: 'configured-model', api_key_configured: true, mode: 'remote', local: false },
    });
    mocks.testPubMedConnection.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối PubMed thành công.' });
    mocks.testLlmConnection.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối OpenAI thành công.' });
    mocks.search.mockReset().mockResolvedValue(searchResponse);
    mocks.importSources.mockReset().mockResolvedValue({
      count: 2,
      created_count: 1,
      reused_count: 1,
      sources: [
        { id: 10, pmid: '12345678', created: true, title: searchResponse.results[0].title, retrieved_at: null },
        { id: 11, pmid: '87654321', created: false, title: searchResponse.results[1].title, retrieved_at: null },
      ],
    });
    mocks.getHistory.mockReset().mockResolvedValue({ topic: null, revisions: [] });
    mocks.generateDraft.mockReset().mockResolvedValue(draftRevision);
    mocks.getRevision.mockReset().mockResolvedValue(draftRevision);
    mocks.updateDraft.mockReset().mockResolvedValue(draftRevision);
  });

  it.each(['admin', 'staff'])('renders the research workspace for %s', async (role) => {
    await renderReadyPage(role);
    expect(screen.getByRole('heading', { name: 'Kho kiến thức y khoa' })).toBeInTheDocument();
  });

  it('blocks an unauthorized role and does not load options', () => {
    mocks.role = 'viewer';
    render(<MedicalKnowledgeResearchPage />);
    expect(screen.getByRole('alert')).toHaveTextContent('Bạn không có quyền');
    expect(mocks.getOptions).not.toHaveBeenCalled();
  });

  it('renders disease ID/name and canonical Vietnamese weather labels', async () => {
    await renderReadyPage();
    expect(screen.getByRole('option', { name: '5 — Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn' })).toBeInTheDocument();
    for (const label of ['Nhiệt độ', 'Độ ẩm', 'Mưa / lượng mưa', 'Gió', 'Điều kiện thời tiết']) {
      expect(screen.getByRole('option', { name: label })).toBeInTheDocument();
    }
  });

  it('keeps search disabled until at least one disease term exists', async () => {
    await renderReadyPage();
    await chooseContext();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' })).toBeDisabled();
    addTerm();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' })).toBeEnabled();
  });

  it('adds and removes a disease term with keyboard-accessible controls', async () => {
    await renderReadyPage();
    addTerm('infectious diarrhea');
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Xóa từ khóa infectious diarrhea' }));
    expect(screen.queryByText('infectious diarrhea')).not.toBeInTheDocument();
  });

  it('does not create a duplicate term', async () => {
    await renderReadyPage();
    addTerm('gastroenteritis');
    addTerm('GASTROENTERITIS');
    expect(screen.getByRole('alert')).toHaveTextContent('đã được thêm');
    expect(screen.getAllByText(/gastroenteritis/i)).toHaveLength(1);
  });

  it('sends the clean search contract and bounded max_results', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('gastroenteritis');
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Số kết quả'), { target: { value: '15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(1));
    expect(mocks.search).toHaveBeenCalledWith({
      disease_group_id: '5',
      weather_factor: 'precipitation',
      disease_terms: ['gastroenteritis'],
      max_results: 15,
      year_from: null,
      year_to: null,
    });
  });

  it('shows a loading state and prevents double submit', async () => {
    mocks.search.mockReturnValue(new Promise(() => undefined));
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    expect(screen.getByRole('button', { name: 'Đang tìm tài liệu…' })).toBeDisabled();
  });

  it('renders a friendly zero-result state', async () => {
    mocks.search.mockResolvedValue({ ...searchResponse, count: 0, results: [] });
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    expect(await screen.findByText('Không tìm thấy tài liệu phù hợp')).toBeInTheDocument();
  });

  it('maps provider failures to a safe Vietnamese error', async () => {
    mocks.search.mockRejectedValue(new ApiError(502, 'provider details'));
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Hiện không thể kết nối PubMed');
    expect(screen.queryByText('provider details')).not.toBeInTheDocument();
  });

  it('renders paper metadata and omits missing DOI safely', async () => {
    await runSuccessfulSearch();
    expect(screen.getByText('Rainfall and pediatric gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('Năm 2024')).toBeInTheDocument();
    expect(screen.getByText('Journal of Pediatric Weather')).toBeInTheDocument();
    expect(screen.getByText('An Nguyen, BC Smith')).toBeInTheDocument();
    const missingCard = screen.getByText('Record without abstract').closest('article')!;
    expect(within(missingCard).queryByText(/DOI:/)).not.toBeInTheDocument();
  });

  it('renders missing abstract text and expands/collapses a long abstract', async () => {
    await runSuccessfulSearch();
    expect(screen.getByText('PubMed không cung cấp tóm tắt cho tài liệu này.')).toBeInTheDocument();
    const expand = screen.getByRole('button', { name: 'Xem tóm tắt đầy đủ' });
    const card = screen.getByText('Rainfall and pediatric gastroenteritis').closest('article')!;
    fireEvent.click(expand);
    expect(within(card).getByText((_, node) => node?.textContent?.trim() === longAbstract.trim())).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Thu gọn' }));
    expect(within(card).queryByText((_, node) => node?.textContent?.trim() === longAbstract.trim())).not.toBeInTheDocument();
  });

  it('tracks paper selection and disables import with zero selected', async () => {
    await runSuccessfulSearch();
    expect(screen.getByRole('button', { name: 'Thêm 0 tài liệu vào kho nguồn' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ }));
    expect(screen.getAllByText('Đã chọn 1 tài liệu').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Thêm 1 tài liệu vào kho nguồn' })).toBeEnabled();
  });

  it('imports only selected PMIDs and explains created/reused counts', async () => {
    await runSuccessfulSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả kết quả' }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 2 tài liệu vào kho nguồn' }));
    await waitFor(() => expect(mocks.importSources).toHaveBeenCalledWith(['12345678', '87654321']));
    expect(await screen.findByRole('status')).toHaveTextContent('1 tài liệu mới đã được lưu');
    expect(screen.getByRole('status')).toHaveTextContent('1 tài liệu đã có sẵn nên được sử dụng lại');
    expect(screen.getAllByText('Đã có trong kho')).toHaveLength(2);
  });

  it('clears stale results and disease terms when disease group changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '1' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('1', 'precipitation'));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    expect(screen.queryByText('gastroenteritis')).not.toBeInTheDocument();
  });

  it('clears stale results but keeps disease terms when weather factor changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('2. Yếu tố thời tiết'), { target: { value: 'humidity' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('5', 'humidity'));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
  });

  it('keeps generated query collapsed before sources are imported', async () => {
    await runSuccessfulSearch();
    const details = screen.getByText('Chi tiết tìm kiếm').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(screen.queryByRole('button', { name: 'Tạo bản nháp bằng AI' })).not.toBeInTheDocument();
  });

  it('shows the AI draft action only after imported DB source IDs exist', async () => {
    await importAllSources();
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeEnabled();
  });

  it('shows a server configuration message while PubMed remains usable', async () => {
    mocks.getOptions.mockResolvedValue({ ...options, llm_draft_generation_available: false });
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByText('Tạo bản nháp bằng AI chưa được cấu hình trên máy chủ.')).toBeInTheDocument();
    addTerm();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' })).toBeEnabled();
  });

  it('shows generation loading wording and prevents double submit', async () => {
    mocks.generateDraft.mockReturnValue(new Promise(() => undefined));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(screen.getByRole('button', { name: 'Đang tạo bản nháp…' })).toBeDisabled();
    expect(screen.getByText(/AI đang đọc tóm tắt/)).toBeInTheDocument();
    expect(mocks.generateDraft).toHaveBeenCalledTimes(1);
  });

  it('maps generation provider errors without exposing raw details', async () => {
    mocks.generateDraft.mockRejectedValue(new ApiError(502, 'raw provider payload'));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AI chưa thể tạo bản nháp hợp lệ');
    expect(screen.queryByText('raw provider payload')).not.toBeInTheDocument();
  });

  it('renders the generated DRAFT review form, source, and AI relevance note', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('heading', { name: 'Revision 2' })).toBeInTheDocument();
    expect(screen.getByText('DRAFT — Chưa xuất bản')).toBeInTheDocument();
    expect(screen.getByLabelText('Mức bằng chứng AI đề xuất')).toHaveValue('LIMITED_OR_INDIRECT');
    expect(screen.getByLabelText('Phạm vi bằng chứng AI đề xuất')).toHaveValue('PARTIAL_GROUP');
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveValue(draftRevision.short_explanation_vi);
    expect(screen.getByLabelText('Giải thích chi tiết')).toHaveValue(draftRevision.detailed_explanation_vi);
    expect(screen.getByLabelText('Giới hạn')).toHaveValue(draftRevision.limitations_vi);
    expect(screen.getByText('DIRECT: Nghiên cứu trực tiếp yếu tố mưa.')).toBeInTheDocument();
  });

  it('sends only editable fields when saving and confirms parents cannot see it', async () => {
    const edited = { ...draftRevision, short_explanation_vi: 'Nội dung nhân viên đã sửa.' };
    mocks.updateDraft.mockResolvedValue(edited);
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.change(screen.getByLabelText('Giải thích ngắn'), { target: { value: edited.short_explanation_vi } });
    fireEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }));
    await waitFor(() => expect(mocks.updateDraft).toHaveBeenCalledTimes(1));
    expect(mocks.updateDraft).toHaveBeenCalledWith(21, {
      evidence_level: 'LIMITED_OR_INDIRECT',
      evidence_scope: 'PARTIAL_GROUP',
      short_explanation_vi: edited.short_explanation_vi,
      detailed_explanation_vi: draftRevision.detailed_explanation_vi,
      limitations_vi: draftRevision.limitations_vi,
    });
    expect(await screen.findByText(/Nội dung này chưa hiển thị cho phụ huynh/)).toBeInTheDocument();
  });

  it('loads history for each selected disease/weather context and reopens a DRAFT', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [draftRevision],
    });
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByRole('button', { name: 'Revision 2 — DRAFT' })).toBeInTheDocument();
    expect(mocks.getHistory).toHaveBeenCalledWith('5', 'precipitation');
    fireEvent.click(screen.getByRole('button', { name: 'Revision 2 — DRAFT' }));
    expect(await screen.findByRole('heading', { name: 'Revision 2' })).toBeInTheDocument();
    expect(mocks.getRevision).toHaveBeenCalledWith(21);
  });

  it.each(['APPROVED', 'REJECTED'] as const)('opens %s revisions read-only', async (status) => {
    const readOnlyRevision = { ...draftRevision, status };
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: status === 'APPROVED' ? 21 : null,
      },
      revisions: [readOnlyRevision],
    });
    mocks.getRevision.mockResolvedValue(readOnlyRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: `Revision 2 — ${status}` }));
    expect(await screen.findByText(`${status} — Chỉ đọc`)).toBeInTheDocument();
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Lưu bản nháp' })).not.toBeInTheDocument();
  });

  it('does not expose approve or publish actions', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    expect(screen.queryByRole('button', { name: /approve|publish|duyệt|xuất bản/i })).not.toBeInTheDocument();
  });
});
