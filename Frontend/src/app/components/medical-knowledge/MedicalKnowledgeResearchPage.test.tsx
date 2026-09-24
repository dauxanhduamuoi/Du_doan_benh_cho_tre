import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import type {
  DraftRevision,
  MedicalKnowledgeOptions,
  PubMedSearchResponse,
  ReviewedProviderSearchResponse,
  TopicSourceLibrary,
} from '@/lib/medicalKnowledgeApi';
import MedicalKnowledgeResearchPage, {
  getDefaultPubMedDiseaseKeyword,
  resolveKnowledgeView,
} from './MedicalKnowledgeResearchPage';

const mocks = vi.hoisted(() => ({
  role: 'admin',
  getOptions: vi.fn(),
  getServiceStatus: vi.fn(),
  testPubMedConnection: vi.fn(),
  testLlmConnection: vi.fn(),
  search: vi.fn(),
  lookupPmid: vi.fn(),
  importSources: vi.fn(),
  getTopicSources: vi.fn(),
  getHistory: vi.fn(),
  generateDraft: vi.fn(),
  getRevision: vi.fn(),
  updateDraft: vi.fn(),
  approveRevision: vi.fn(),
  publishRevision: vi.fn(),
  unpublishRevision: vi.fn(),
  getAutoOverview: vi.fn(),
  getProviderSettings: vi.fn(),
  searchProviders: vi.fn(),
  importProviderSources: vi.fn(),
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
    lookupPubMedByPmid: mocks.lookupPmid,
    importPubMedSources: mocks.importSources,
    getMedicalKnowledgeTopicSources: mocks.getTopicSources,
    getMedicalKnowledgeDraftHistory: mocks.getHistory,
    generateMedicalKnowledgeDraft: mocks.generateDraft,
    getMedicalKnowledgeRevision: mocks.getRevision,
    updateMedicalKnowledgeDraft: mocks.updateDraft,
    approveMedicalKnowledgeRevision: mocks.approveRevision,
    publishMedicalKnowledgeRevision: mocks.publishRevision,
    unpublishMedicalKnowledgeRevision: mocks.unpublishRevision,
    getAutoMedicalKnowledgeOverview: mocks.getAutoOverview,
    getMedicalEvidenceProviderSettings: mocks.getProviderSettings,
    searchMedicalEvidenceProviders: mocks.searchProviders,
    importMedicalEvidenceProviderSources: mocks.importProviderSources,
  };
});

const options: MedicalKnowledgeOptions = {
  disease_groups: [
    { id: '1', name: 'Tả - Cholera' },
    {
      id: '5',
      name: 'Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn - Display label must not win',
      english_name: 'gastroenteritis',
    },
    { id: '168', name: 'Cúm - Influenza' },
    {
      id: '170',
      name: 'Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis',
    },
  ],
  weather_factors: [
    { value: 'temperature', label_vi: 'Nhiệt độ' },
    { value: 'humidity', label_vi: 'Độ ẩm' },
    { value: 'precipitation', label_vi: 'Mưa / lượng mưa' },
    { value: 'wind', label_vi: 'Gió' },
    { value: 'weather_condition', label_vi: 'Điều kiện thời tiết' },
  ],
  explanation_factors: [
    { type: 'AGE', key: 'age_group', label_vi: 'Độ tuổi', values: ['1-5 tuổi', '6-10 tuổi'] },
    { type: 'SEX', key: 'gender', label_vi: 'Giới tính', values: ['Nam', 'Nữ'] },
    { type: 'SEASONALITY', key: 'time_of_year', label_vi: 'Tính mùa vụ', values: [] },
    { type: 'WEATHER', key: 'precipitation', label_vi: 'Mưa / lượng mưa', values: [] },
    { type: 'WEATHER', key: 'humidity', label_vi: 'Độ ẩm', values: [] },
    { type: 'WEATHER', key: 'temperature', label_vi: 'Nhiệt độ', values: [] },
    { type: 'WEATHER', key: 'wind', label_vi: 'Gió', values: [] },
    { type: 'WEATHER', key: 'weather_condition', label_vi: 'Điều kiện thời tiết', values: [] },
  ],
  llm_draft_generation_available: true,
};

const longAbstract = 'Nghiên cứu quan sát mô tả mối liên hệ theo thời gian. '.repeat(10);
const searchResponse: PubMedSearchResponse = {
  disease_group_id: '5',
  factor_type: 'WEATHER',
  factor_key: 'precipitation',
  factor_value: null,
  weather_factor: 'precipitation',
  search_mode: 'GUIDED',
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

const multiProviderSearchResponse: ReviewedProviderSearchResponse = {
  requested_count: 10,
  provider_count: 2,
  max_candidates: 20,
  count: 2,
  unique_count: 2,
  queries: { PUBMED: 'pubmed query', WHO: 'who query' },
  warnings: [],
  providers: [
    {
      provider_id: 'PUBMED', display_name: 'PubMed / PMC', requested_count: 10,
      requested_relevant_count: 10, effective_limit: 10, returned_count: 1, total_available: 24, provider_total_available: 24,
      provider_invoked: true, provider_status: 'SUCCESS',
      raw_result_count: 1, raw_candidates_examined: 1, normalized_count: 1, normalized_candidates: 1, disease_match_count: 1, factor_match_count: 1,
      relevant_count: 1, rejected_count: 0, pages_fetched: 1, budget_exhausted: false, provider_exhausted: false, stop_reason: 'QUERY_PLAN_EXHAUSTED', direct_count: 1, related_count: 0, contextual_count: 0,
      status: 'SUCCESS', query: 'pubmed query', warning: null,
      query_attempts: [{ level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC', relevance: 'DIRECT_TOPIC', query: 'pubmed query', provider_match_count: 24, fetched_count: 1, normalized_count: 1, disease_match_count: 1, factor_match_count: 1, relevant_count: 1, direct_count: 1, related_count: 0, rejected_count: 0, pages_fetched: 1, budget_exhausted: false, provider_exhausted: false, stop_reason: 'QUERY_ATTEMPT_COMPLETE', status: 'SUCCESS', warning: null }],
      results: [],
    },
    {
      provider_id: 'WHO', display_name: 'World Health Organization (WHO)', requested_count: 10,
      requested_relevant_count: 10, effective_limit: 10, returned_count: 1, total_available: 5, provider_total_available: 5,
      provider_invoked: true, provider_status: 'SUCCESS',
      raw_result_count: 1, raw_candidates_examined: 1, normalized_count: 1, normalized_candidates: 1, disease_match_count: 1, factor_match_count: 1,
      relevant_count: 1, rejected_count: 0, pages_fetched: 1, budget_exhausted: false, provider_exhausted: true, stop_reason: 'PROVIDER_EXHAUSTED', direct_count: 1, related_count: 0, contextual_count: 0,
      status: 'SUCCESS', query: 'who query', warning: null,
      query_attempts: [{ level: 'DIRECT_DISEASE_FACTOR', relevance: 'DIRECT_TOPIC', query: 'who query', provider_match_count: 5, fetched_count: 1, normalized_count: 1, disease_match_count: 1, factor_match_count: 1, relevant_count: 1, direct_count: 1, related_count: 0, rejected_count: 0, pages_fetched: 1, budget_exhausted: false, provider_exhausted: true, stop_reason: 'PROVIDER_EXHAUSTED', status: 'SUCCESS', warning: null }],
      results: [],
    },
  ],
  results: [
    {
      provider_id: 'PUBMED', external_id: '12345678', source_kind: 'RESEARCH_ARTICLE',
      title: 'PubMed mixed evidence', authors: 'Fixture Author',
      publisher_or_journal: 'Fixture Journal', publication_date: '2025-01-01',
      publication_year: 2025, doi: '10.1000/mixed',
      url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/', abstract_text: 'Evidence',
      license_name: null, license_url: null, usability: 'USABLE_FOR_DRAFT' as const,
      usable_for_draft: true, source_id: null, in_topic_library: false,
      relevance: 'DIRECT_TOPIC', query_level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC',
    },
    {
      provider_id: 'WHO', external_id: '73164', source_kind: 'OTHER',
      title: 'WHO influenza metadata record', authors: null,
      publisher_or_journal: 'World Health Organization', publication_date: '2025-02-01',
      publication_year: 2025, doi: null,
      url: 'https://www.who.int/publications/b/73164', abstract_text: 'Metadata summary',
      license_name: null, license_url: null, usability: 'METADATA_ONLY' as const,
      usable_for_draft: false, source_id: null, in_topic_library: false,
      relevance: 'DIRECT_TOPIC', query_level: 'DIRECT_DISEASE_FACTOR',
    },
  ],
};

multiProviderSearchResponse.providers[0].results = [multiProviderSearchResponse.results[0]];
multiProviderSearchResponse.providers[1].results = [multiProviderSearchResponse.results[1]];

const mixedTopicLibrary: TopicSourceLibrary = {
  topic_id: 7,
  disease_group_id: '5',
  factor_type: 'WEATHER',
  factor_key: 'precipitation',
  factor_value: null,
  weather_factor: 'precipitation',
  sources: [
    {
      source_id: 30, provider_id: 'WHO', external_id: '73164', source_kind: 'OTHER',
      pmid: null, title: 'WHO influenza metadata record', journal: 'World Health Organization',
      publication_year: 2025, doi: null, pmcid: null, content_kind: null,
      url: 'https://www.who.int/publications/b/73164', license_name: null,
      license_url: null, usable_for_draft: false, added_at: '2026-09-12T10:00:00',
    },
    {
      source_id: 31, provider_id: 'PUBMED', external_id: '12345678',
      source_kind: 'RESEARCH_ARTICLE', pmid: '12345678', title: 'PubMed mixed evidence',
      journal: 'Fixture Journal', publication_year: 2025, doi: '10.1000/mixed',
      pmcid: null, content_kind: 'ABSTRACT', url: 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
      license_name: null, license_url: null, usable_for_draft: true,
      added_at: '2026-09-12T10:01:00',
    },
  ],
};

const populatedTopicLibrary = {
  topic_id: 7,
  disease_group_id: '5',
  weather_factor: 'precipitation',
  sources: [
    {
      source_id: 10,
      pmid: '12345678',
      title: searchResponse.results[0].title,
      journal: 'Journal of Pediatric Weather',
      publication_year: 2024,
      doi: '10.1000/rain',
      pmcid: 'PMC123456',
      content_kind: 'PMC_FULL_TEXT_EXCERPT' as const,
      added_at: '2026-08-24T00:00:00',
    },
    {
      source_id: 11,
      pmid: '87654321',
      title: searchResponse.results[1].title,
      journal: null,
      publication_year: null,
      doi: null,
      pmcid: null,
      content_kind: 'ABSTRACT' as const,
      added_at: '2026-08-24T00:01:00',
    },
  ],
};

function capacityTopicLibrary(
  count: number,
  unusableSourceIds: number[] = [],
): TopicSourceLibrary {
  return {
    topic_id: 77,
    disease_group_id: '5',
    factor_type: 'WEATHER',
    factor_key: 'precipitation',
    factor_value: null,
    weather_factor: 'precipitation',
    sources: Array.from({ length: count }, (_, index) => {
      const sourceId = index + 1;
      return {
        source_id: sourceId,
        pmid: String(90000000 + sourceId),
        title: `Capacity source ${sourceId}`,
        journal: 'Capacity Journal',
        publication_year: 2026,
        doi: null,
        pmcid: null,
        content_kind: unusableSourceIds.includes(sourceId) ? null : 'ABSTRACT',
        added_at: `2026-08-27T00:${String(index).padStart(2, '0')}:00`,
      };
    }),
  };
}

const weatherSelector = (key: string) => ({
  factor_type: 'WEATHER' as const,
  factor_key: key,
  factor_value: null,
  weather_factor: key,
});

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
  factor_type: 'WEATHER',
  factor_key: 'precipitation',
  factor_value: null,
  disease_group_name: 'Tiêu chảy / viêm dạ dày-ruột nghi nhiễm khuẩn',
  weather_factor: 'precipitation',
  short_explanation_vi: 'Mưa có liên hệ quan sát với một phần nhóm bệnh.',
  detailed_explanation_vi: 'Nghiên cứu ghi nhận mối liên hệ ở mức quần thể, chưa chứng minh nhân quả.',
  limitations_vi: 'Nguồn chỉ nghiên cứu một subtype và không dự đoán nguy cơ cá nhân.',
  parent_display_allowed: false,
  llm_model: 'configured-model',
  prompt_version: 'medical_knowledge_v3_pediatric_population',
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
      content_kind: 'PMC_FULL_TEXT_EXCERPT',
      pmcid: 'PMC123456',
      content_origin: 'NCBI_PMC',
      source_role: 'PRIMARY',
      sort_order: 0,
      relevance_note: 'DIRECT: Nghiên cứu trực tiếp yếu tố mưa.',
      population_relevance: 'PEDIATRIC_DIRECT',
      population_note: 'Abstract mô tả trực tiếp trẻ em.',
    },
  ],
  parent_tier2_eligible: true,
  parent_tier2_ineligibility_reasons: [],
};

const approvedRevision: DraftRevision = {
  ...draftRevision,
  status: 'APPROVED',
  reviewed_by: 1,
  reviewed_by_name: 'Bác sĩ kiểm duyệt',
  reviewed_at: '2026-08-23T09:30:00',
  updated_at: '2026-08-23T09:30:00',
};

const publishedRevision: DraftRevision = {
  ...approvedRevision,
  is_published: true,
  parent_display_allowed: true,
  published_by: 2,
  published_by_name: 'Điều phối xuất bản',
  published_at: '2026-08-23T10:00:00',
};

async function renderReadyPage(role = 'admin') {
  mocks.role = role;
  render(<MedicalKnowledgeResearchPage />);
  await screen.findByRole('option', { name: /5 — Tiêu chảy/ });
}

async function chooseContext() {
  fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '5' } });
  fireEvent.change(screen.getByLabelText('2. Yếu tố cần giải thích'), { target: { value: 'WEATHER:precipitation' } });
  await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('5', {
    factor_type: 'WEATHER',
    factor_key: 'precipitation',
    factor_value: null,
    weather_factor: 'precipitation',
  }));
}

function addTerm(term = 'gastroenteritis') {
  const chips = screen.queryByLabelText('Các từ khóa đã thêm');
  if (chips && within(chips).queryByText(term)) return;
  const input = screen.getByLabelText('3. Từ khóa tìm kiếm');
  fireEvent.change(input, { target: { value: term } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
}

function switchToFreeSearch(query = 'gastroenteritis rainfall children') {
  fireEvent.click(screen.getByRole('button', { name: 'Tìm kiếm PubMed tự do' }));
  fireEvent.change(screen.getByLabelText('Truy vấn PubMed tự do'), {
    target: { value: query },
  });
}

async function runSuccessfulSearch() {
  await renderReadyPage();
  await chooseContext();
  addTerm();
  switchToFreeSearch();
  fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
  await screen.findByRole('heading', { name: /Tìm thấy \d+ tài liệu/ });
}

async function importAllSources() {
  await runSuccessfulSearch();
  mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
  fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả kết quả' }));
  fireEvent.click(screen.getByRole('button', { name: 'Thêm 2 tài liệu vào kho chủ đề' }));
  await screen.findByText('2 tài liệu đã lưu');
  fireEvent.click(screen.getByRole('checkbox', { name: /Rainfall.*cho bản nháp/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Record without abstract.*cho bản nháp/ }));
  expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeEnabled();
}

function enableWhoReviewed() {
  mocks.getProviderSettings.mockResolvedValue({ providers: [
    { provider_id: 'PUBMED', display_name: 'PubMed / PMC', description: 'Research', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
    { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', description: 'Official', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
  ] });
  mocks.searchProviders.mockResolvedValue(multiProviderSearchResponse);
}

function singleProviderResponse(
  group: ReviewedProviderSearchResponse['providers'][number],
): ReviewedProviderSearchResponse {
  return {
    requested_count: 10,
    provider_count: 1,
    max_candidates: group.effective_limit,
    count: group.returned_count,
    unique_count: group.returned_count,
    queries: { [group.provider_id]: group.query },
    warnings: group.warning ? [group.warning] : [],
    providers: [group],
    results: group.results,
  };
}

async function selectWhoOnlyAndSearch() {
  await renderReadyPage();
  await chooseContext();
  fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'PubMed / PMC' }));
  fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
  await screen.findByRole('heading', { name: 'Kết quả theo nguồn' });
}

async function runMultiProviderSearch() {
  enableWhoReviewed();
  await renderReadyPage();
  await chooseContext();
  fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
  fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
  await screen.findByRole('heading', { name: 'Kết quả theo nguồn' });
}

async function providerResultCheckbox(title: string): Promise<HTMLElement> {
  const providerName = title.startsWith('WHO') ? /World Health Organization/ : /PubMed \/ PMC/;
  let panel = screen.queryByRole('tabpanel', { name: providerName });
  if (!panel) {
    fireEvent.click(screen.getByRole('tab', { name: providerName }));
    panel = await screen.findByRole('tabpanel', { name: providerName });
  }
  const result = within(panel).queryByRole('checkbox', { name: new RegExp(title) });
  if (!result) throw new Error(`Provider result checkbox was not found: ${title}`);
  return result;
}

function importResponse(
  sources: Array<Record<string, unknown>>,
  overrides: Record<string, unknown> = {},
) {
  const failed = sources.filter((item) => item.outcome === 'REJECTED_INVALID' || item.outcome === 'PROVIDER_ERROR').length;
  const added = sources.filter((item) => item.outcome === 'ADDED' || item.outcome === 'ADDED_REFERENCE_ONLY').length;
  return {
    topic_id: added ? 7 : null,
    count: sources.length - failed,
    requested_count: sources.length,
    added_count: added,
    reference_only_count: sources.filter((item) => item.outcome === 'ADDED_REFERENCE_ONLY').length,
    already_exists_count: sources.filter((item) => item.outcome === 'ALREADY_EXISTS').length,
    failed_count: failed,
    sources,
    ...overrides,
  };
}

const whoReferenceOutcome = {
  outcome: 'ADDED_REFERENCE_ONLY', source_id: 30, provider_id: 'WHO', external_id: '73164',
  title: 'WHO influenza metadata record', created: true, topic_link_created: true,
  content_kind: null, license_name: null, license_url: null, usable_for_draft: false,
  imported_at: '2026-09-12T10:00:00', message: null,
};

const pubmedAddedOutcome = {
  outcome: 'ADDED', source_id: 31, provider_id: 'PUBMED', external_id: '12345678',
  title: 'PubMed mixed evidence', created: true, topic_link_created: true,
  content_kind: 'ABSTRACT', license_name: null, license_url: null, usable_for_draft: true,
  imported_at: '2026-09-12T10:00:00', message: null,
};

describe('MedicalKnowledgeResearchPage', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/?section=medical-knowledge');
    mocks.role = 'admin';
    mocks.getOptions.mockReset().mockResolvedValue(options);
    mocks.getServiceStatus.mockReset().mockResolvedValue({
      pubmed: { configured: true, email_configured: true, api_key_configured: false },
      llm: { configured: true, provider: 'openai', model: 'configured-model', api_key_configured: true, mode: 'remote', local: false },
    });
    mocks.testPubMedConnection.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối PubMed thành công.' });
    mocks.testLlmConnection.mockReset().mockResolvedValue({ ok: true, message: 'Kết nối OpenAI thành công.' });
    mocks.search.mockReset().mockResolvedValue(searchResponse);
    mocks.getProviderSettings.mockReset().mockResolvedValue({ providers: [
      { provider_id: 'PUBMED', display_name: 'PubMed / PMC', description: 'Research', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
    ] });
    mocks.searchProviders.mockReset().mockResolvedValue({
      requested_count: 10, provider_count: 0, max_candidates: 0,
      count: 0, unique_count: 0, providers: [], results: [], queries: {}, warnings: [],
    });
    mocks.importProviderSources.mockReset().mockResolvedValue(importResponse([whoReferenceOutcome]));
    mocks.lookupPmid.mockReset().mockResolvedValue({
      pmid: '34201085',
      result: {
        pmid: '34201085',
        title: 'Lagged Association between Climate Variables and Hospital Admissions for Pneumonia in South Africa',
        authors: 'Caradee Y Wright',
        journal: 'International Journal of Environmental Research and Public Health',
        publication_year: 2021,
        doi: '10.3390/ijerph18136971',
        abstract_text: 'This study investigated pneumonia admissions, temperature and relative humidity.',
        pubmed_url: 'https://pubmed.ncbi.nlm.nih.gov/34201085/',
      },
      existing_source: null,
    });
    mocks.importSources.mockReset().mockResolvedValue({
      topic_id: 7,
      count: 2,
      created_count: 1,
      reused_count: 1,
      sources: [
        {
          id: 10,
          pmid: '12345678',
          created: true,
          title: searchResponse.results[0].title,
          retrieved_at: null,
          content_kind: 'PMC_FULL_TEXT_EXCERPT',
          pmcid: 'PMC123456',
          source_reused: false,
          topic_link_created: true,
          already_in_topic_library: false,
        },
        {
          id: 11,
          pmid: '87654321',
          created: false,
          title: searchResponse.results[1].title,
          retrieved_at: null,
          content_kind: 'ABSTRACT',
          pmcid: null,
          source_reused: true,
          topic_link_created: true,
          already_in_topic_library: false,
        },
      ],
    });
    mocks.getTopicSources.mockReset().mockResolvedValue({
      topic_id: null,
      disease_group_id: '5',
      weather_factor: 'precipitation',
      sources: [],
    });
    mocks.getHistory.mockReset().mockResolvedValue({ topic: null, revisions: [] });
    mocks.generateDraft.mockReset().mockResolvedValue(draftRevision);
    mocks.getRevision.mockReset().mockResolvedValue(draftRevision);
    mocks.updateDraft.mockReset().mockResolvedValue(draftRevision);
    mocks.approveRevision.mockReset().mockResolvedValue({
      revision_id: 21,
      status: 'APPROVED',
      approved_by: 1,
      approved_by_name: 'Bác sĩ kiểm duyệt',
      approved_at: '2026-08-23T09:30:00',
      parent_display_allowed: false,
      published_revision_id: null,
    });
    mocks.publishRevision.mockReset().mockResolvedValue({
      revision_id: 21,
      topic_id: 7,
      status: 'APPROVED',
      is_published: true,
      parent_display_allowed: true,
      published_by: 2,
      published_by_name: 'Điều phối xuất bản',
      published_at: '2026-08-23T10:00:00',
      previous_published_revision_id: null,
    });
    mocks.unpublishRevision.mockReset().mockResolvedValue({
      revision_id: 21,
      topic_id: 7,
      status: 'APPROVED',
      is_published: false,
      parent_display_allowed: false,
      unpublished_by: 1,
      unpublished_by_name: 'Bác sĩ kiểm duyệt',
      unpublished_at: '2026-08-24T08:00:00',
    });
    mocks.getAutoOverview.mockReset().mockResolvedValue({
      settings: { enabled: false, display_mode: 'REVIEWED_ONLY', auto_visible_default: false },
      provider_cooldown: null,
      jobs: [],
      revisions: [],
    });
  });

  it('defaults invalid knowledgeView values to the reviewed workspace', () => {
    expect(resolveKnowledgeView('?section=medical-knowledge&knowledgeView=invalid')).toBe('reviewed');
    expect(resolveKnowledgeView('?section=medical-knowledge&knowledgeView=auto')).toBe('auto');
  });

  it('keeps the reviewed/auto workspace choice in the URL and restores it on popstate', async () => {
    await renderReadyPage();
    fireEvent.click(screen.getByRole('button', { name: /Kiến thức tự động/ }));
    expect(new URLSearchParams(window.location.search).get('knowledgeView')).toBe('auto');
    expect(await screen.findByRole('heading', { name: 'Auto Medical Knowledge' })).toBeVisible();

    act(() => {
      window.history.pushState({}, '', '/?section=medical-knowledge&knowledgeView=reviewed');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(await screen.findByRole('heading', { name: 'Chủ đề đang làm việc' })).toBeVisible();
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
    expect(screen.queryByRole('button', { name: 'Duyệt bản này' })).not.toBeInTheDocument();
  });

  it('renders disease ID/name and canonical Vietnamese weather labels', async () => {
    await renderReadyPage();
    expect(screen.getByRole('option', { name: /5 — Tiêu chảy/ })).toBeInTheDocument();
    expect(screen.getByText('Tìm kiếm mặc định ưu tiên các nghiên cứu trên trẻ em.')).toBeInTheDocument();
    for (const label of ['Nhiệt độ', 'Độ ẩm', 'Mưa / lượng mưa', 'Gió', 'Điều kiện thời tiết']) {
      expect(screen.getByRole('option', { name: label })).toBeInTheDocument();
    }
  });

  it('enables search immediately after the selected disease supplies its default term', async () => {
    await renderReadyPage();
    await chooseContext();
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu' })).toBeEnabled();
  });

  it('prefers a structured English name over parsing the display label', () => {
    expect(getDefaultPubMedDiseaseKeyword({
      id: '5',
      name: 'Nhãn tiếng Việt - Parsed value must not win',
      english_name: 'Structured gastroenteritis',
    })).toBe('Structured gastroenteritis');
  });

  it('parses the first catalog separator and preserves separators inside English text', () => {
    expect(getDefaultPubMedDiseaseKeyword({
      id: '117',
      name: 'Tên tiếng Việt - Neurotic, stress - related and somatoform disorders',
    })).toBe('Neurotic, stress - related and somatoform disorders');
    expect(getDefaultPubMedDiseaseKeyword({ id: '313', name: 'Nhãn không có English delimiter' })).toBeNull();
  });

  it('changes the default keyword when the disease changes and supports the long group name', async () => {
    await renderReadyPage();
    await chooseContext();
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '170' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('170', weatherSelector('precipitation')));
    expect(screen.queryByText('gastroenteritis')).not.toBeInTheDocument();
    expect(screen.getByText('Acute bronchitis and acute bronchiolitis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu' })).toBeEnabled();
  });

  it('lets the user delete and restore exactly one default keyword', async () => {
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('button', { name: 'Xóa từ khóa gastroenteritis' }));
    expect(screen.queryByText('gastroenteritis')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tìm tài liệu' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Khôi phục từ khóa mặc định' }));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Khôi phục từ khóa mặc định' })).not.toBeInTheDocument();
  });

  it('lets the user add synonyms and restore without duplicating the default', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Khôi phục từ khóa mặc định' }));
    expect(screen.getAllByText('gastroenteritis')).toHaveLength(1);
    expect(screen.queryByText('infectious diarrhea')).not.toBeInTheDocument();
  });

  it('keeps the existing eight-keyword limit after auto-fill', async () => {
    await renderReadyPage();
    await chooseContext();
    for (let index = 1; index <= 7; index += 1) addTerm(`synonym ${index}`);
    addTerm('one keyword too many');
    expect(screen.getByRole('alert')).toHaveTextContent('tối đa 8 từ khóa');
    expect(within(screen.getByLabelText('Các từ khóa đã thêm')).getAllByRole('button')).toHaveLength(8);
  });

  it('does not reset custom keywords when another PubMed search runs', async () => {
    const pubmed = multiProviderSearchResponse.providers[0];
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(pubmed));
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await screen.findByRole('heading', { name: 'Kết quả theo nguồn' });
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
  });

  it('does not reset custom keywords during direct PMID lookup', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));
    await screen.findByRole('heading', { name: 'Kết quả theo PMID' });
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
  });

  it('does not reset custom keywords when sources are added to the topic library', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    switchToFreeSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    await screen.findByRole('heading', { name: /Tìm thấy \d+ tài liệu/ });
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả kết quả' }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 2 tài liệu vào kho chủ đề' }));
    await screen.findByText('2 tài liệu đã lưu');
    fireEvent.click(screen.getByRole('button', { name: 'Tìm có hướng dẫn' }));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
  });

  it('preserves custom disease keywords when only weather factor changes', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    fireEvent.change(screen.getByLabelText('2. Yếu tố cần giải thích'), { target: { value: 'WEATHER:humidity' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('5', weatherSelector('humidity')));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText('Số kết quả mỗi nguồn'), { target: { value: '15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await waitFor(() => expect(mocks.searchProviders).toHaveBeenCalledTimes(1));
    expect(mocks.searchProviders).toHaveBeenCalledWith({
      disease_group_id: '5',
      factor_type: 'WEATHER',
      factor_key: 'precipitation',
      factor_value: null,
      weather_factor: 'precipitation',
      disease_terms: ['gastroenteritis'],
      provider_ids: ['PUBMED'],
      max_results: 15,
      year_from: null,
      year_to: null,
    });
  });

  it('renders direct PMID lookup and its helper text inside advanced options', async () => {
    await renderReadyPage();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    expect(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID')).toBeInTheDocument();
    expect(screen.getByText(/Chỉ áp dụng cho PubMed \/ PMC/)).toBeInTheDocument();
  });

  it('accepts a numeric PMID and renders the exact result with the current card', async () => {
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    await waitFor(() => expect(mocks.lookupPmid).toHaveBeenCalledWith('34201085', '5', weatherSelector('precipitation')));
    expect(await screen.findByRole('heading', { name: 'Kết quả theo PMID' })).toBeInTheDocument();
    expect(screen.getByText(/Lagged Association between Climate Variables/)).toBeInTheDocument();
    expect(screen.getByText('PMID: 34201085')).toBeInTheDocument();
    expect(screen.queryByText('Chi tiết tìm kiếm')).not.toBeInTheDocument();
  });

  it('rejects invalid direct PMID input clearly without calling the backend', async () => {
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), {
      target: { value: '34201085 OR pneumonia' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    expect(screen.getByRole('alert')).toHaveTextContent('PMID chỉ gồm các chữ số.');
    expect(mocks.lookupPmid).not.toHaveBeenCalled();
    expect(mocks.searchProviders).not.toHaveBeenCalled();
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('keeps an unrelated exact PMID visible and clears old Guided groups', async () => {
    await runMultiProviderSearch();
    mocks.lookupPmid.mockResolvedValue({ pmid: '36071812', result: {
      ...searchResponse.results[0], pmid: '36071812',
      title: 'The temperature-dependent conformational ensemble of SARS-CoV-2 main protease (Mpro).',
      abstract_text: 'COVID-19 continues to plague the globe. High humidity structures.',
      pubmed_url: 'https://pubmed.ncbi.nlm.nih.gov/36071812/',
    }, existing_source: null });
    const searches = mocks.searchProviders.mock.calls.length;
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '36071812' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));
    expect(await screen.findByRole('heading', { name: 'Kết quả theo PMID' })).toBeInTheDocument();
    expect(screen.getByText(/The temperature-dependent conformational ensemble/)).toBeInTheDocument();
    expect(screen.getByText(/Tài liệu chính xác theo PMID, không lọc/)).toBeInTheDocument();
    expect(screen.queryByRole('tablist', { name: 'Kết quả theo nguồn' })).not.toBeInTheDocument();
    expect(mocks.searchProviders).toHaveBeenCalledTimes(searches);
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('refuses a mismatched PMID response instead of substituting a result', async () => {
    mocks.lookupPmid.mockResolvedValue({ pmid: '123', result: { ...searchResponse.results[0], pmid: '999' } });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('heading', { name: 'Kết quả theo PMID' })).not.toBeInTheDocument();
    expect(mocks.search).not.toHaveBeenCalled();
    expect(mocks.searchProviders).not.toHaveBeenCalled();
  });

  it('shows a direct PMID loading state and prevents a double request', async () => {
    mocks.lookupPmid.mockReturnValue(new Promise(() => undefined));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    expect(screen.getByRole('button', { name: 'Đang tìm bài…' })).toBeDisabled();
    expect(mocks.lookupPmid).toHaveBeenCalledTimes(1);
  });

  it('shows a friendly not-found message for a numeric PMID', async () => {
    mocks.lookupPmid.mockRejectedValue(new ApiError(404, 'provider detail'));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '99999999' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Không tìm thấy bài PubMed với PMID này.');
    expect(screen.queryByText('provider detail')).not.toBeInTheDocument();
  });

  it('maps direct PMID provider failures to the existing safe PubMed message', async () => {
    mocks.lookupPmid.mockRejectedValue(new ApiError(502, 'raw XML provider detail'));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Hiện không thể kết nối PubMed');
    expect(screen.queryByText('raw XML provider detail')).not.toBeInTheDocument();
  });

  it('shows the existing-source and evidence badges on an exact PMID result', async () => {
    const exactResult = {
      pmid: '34201085',
      title: 'Existing pneumonia evidence',
      authors: 'Researcher',
      journal: 'Medical Journal',
      publication_year: 2021,
      doi: null,
      abstract_text: 'Abstract',
      pubmed_url: 'https://pubmed.ncbi.nlm.nih.gov/34201085/',
      source_id: 42,
      stored_globally: true,
      in_topic_library: true,
      content_kind: 'PMC_FULL_TEXT' as const,
      pmcid: 'PMC8228646',
    };
    mocks.lookupPmid.mockReset().mockResolvedValue({
      pmid: '34201085',
      result: exactResult,
      existing_source: {
        id: 42,
        pmid: '34201085',
        created: false,
        title: exactResult.title,
        retrieved_at: '2026-08-23T00:00:00',
        content_kind: 'PMC_FULL_TEXT',
        pmcid: 'PMC8228646',
      },
    });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));

    expect(await screen.findByText('Đã có trong kho chủ đề')).toBeInTheDocument();
    expect(screen.getByText('AI sử dụng: Toàn văn PMC')).toBeInTheDocument();
    expect(screen.getByText('PMC8228646')).toBeInTheDocument();
  });

  it('replaces keyword results with the exact PMID result and reuses normal import', async () => {
    await runSuccessfulSearch();
    fireEvent.click(screen.getByText('Tùy chọn nâng cao'));
    fireEvent.change(screen.getByLabelText('Tra cứu trực tiếp PubMed bằng PMID'), { target: { value: '34201085' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm bài' }));
    await screen.findByRole('heading', { name: 'Kết quả theo PMID' });

    expect(screen.queryByText('Rainfall and pediatric gastroenteritis')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Lagged Association/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 tài liệu vào kho chủ đề' }));
    await waitFor(() => expect(mocks.importSources).toHaveBeenCalledWith('5', weatherSelector('precipitation'), ['34201085']));
  });

  it('shows a loading state and prevents double submit', async () => {
    mocks.searchProviders.mockReturnValue(new Promise(() => undefined));
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    expect(screen.getByRole('button', { name: 'Đang tìm tài liệu…' })).toBeDisabled();
  });

  it('renders a friendly zero-result state', async () => {
    mocks.search.mockResolvedValue({ ...searchResponse, count: 0, results: [] });
    await renderReadyPage();
    await chooseContext();
    addTerm();
    switchToFreeSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    expect(await screen.findByText('Không tìm thấy tài liệu phù hợp')).toBeInTheDocument();
  });

  it('maps provider failures to a safe Vietnamese error', async () => {
    mocks.searchProviders.mockRejectedValue(new ApiError(502, 'provider details'));
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
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
    expect(screen.getByRole('button', { name: 'Thêm 0 tài liệu vào kho chủ đề' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ }));
    expect(screen.getAllByText('Đã chọn 1 tài liệu').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Thêm 1 tài liệu vào kho chủ đề' })).toBeEnabled();
    expect(screen.getByText('0 tài liệu')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
  });

  it('does not offer an already-in-topic result for another import', async () => {
    mocks.search.mockResolvedValue({
      ...searchResponse,
      count: 1,
      results: [{
        ...searchResponse.results[0],
        source_id: 10,
        stored_globally: true,
        in_topic_library: true,
        content_kind: 'PMC_FULL_TEXT_EXCERPT',
        pmcid: 'PMC123456',
      }],
    });
    await runSuccessfulSearch();
    expect(screen.getByText('Đã có trong kho chủ đề')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Thêm 0 tài liệu vào kho chủ đề' })).toBeDisabled();
  });

  it('allows a globally stored result to be linked to the current topic', async () => {
    mocks.search.mockResolvedValue({
      ...searchResponse,
      count: 1,
      results: [{
        ...searchResponse.results[0],
        source_id: 10,
        stored_globally: true,
        in_topic_library: false,
        content_kind: 'ABSTRACT',
      }],
    });
    await runSuccessfulSearch();
    expect(screen.getByText('Đã lưu trong hệ thống')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ })).toBeEnabled();
  });

  it('imports only selected PMIDs and explains created/reused counts', async () => {
    await runSuccessfulSearch();
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả kết quả' }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 2 tài liệu vào kho chủ đề' }));
    await waitFor(() => expect(mocks.importSources).toHaveBeenCalledWith('5', weatherSelector('precipitation'), ['12345678', '87654321']));
    expect(await screen.findByRole('status')).toHaveTextContent('1 tài liệu mới đã được lưu');
    expect(screen.getByRole('status')).toHaveTextContent('1 tài liệu đã có sẵn nên được sử dụng lại');
    expect(screen.getAllByText('Đã có trong kho chủ đề')).toHaveLength(2);
    expect(screen.getAllByText('AI sử dụng: Trích đoạn toàn văn PMC').length).toBeGreaterThan(0);
    expect(screen.getAllByText('AI sử dụng: Tóm tắt PubMed').length).toBeGreaterThan(0);
    expect(screen.getByText('PMC123456')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm 0 tài liệu vào kho chủ đề' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
  });

  it('loads the persistent topic library without requiring a new PubMed search', async () => {
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByText('2 tài liệu đã lưu')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Rainfall.*cho bản nháp/ })).toBeInTheDocument();
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('selects all 10 AI-readable sources and sends exactly those 10 to Draft', async () => {
    mocks.getTopicSources.mockResolvedValue(capacityTopicLibrary(10));
    await renderReadyPage();
    await chooseContext();
    await screen.findByText('10 tài liệu đã lưu');

    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả nguồn AI đọc được' }));

    expect(screen.getByText('10 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByText('Tạo bản nháp bằng AI từ 10 nguồn')).toBeInTheDocument();
    for (let sourceId = 1; sourceId <= 10; sourceId += 1) {
      expect(screen.getByRole('checkbox', { name: `Chọn nguồn Capacity source ${sourceId} cho bản nháp` })).toBeChecked();
    }
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await waitFor(() => expect(mocks.generateDraft).toHaveBeenCalledWith({
      disease_group_id: '5',
      factor_type: 'WEATHER',
      factor_key: 'precipitation',
      factor_value: null,
      weather_factor: 'precipitation',
      source_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    }));
  });

  it('clearly applies the 10-source limit when more than 10 usable sources exist', async () => {
    mocks.getTopicSources.mockResolvedValue(capacityTopicLibrary(11));
    await renderReadyPage();
    await chooseContext();
    await screen.findByText('11 tài liệu đã lưu');

    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả nguồn AI đọc được' }));

    expect(screen.getByText('10 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByText(/Có 11 nguồn AI đọc được.*tối đa 10 nguồn/)).toBeInTheDocument();
    expect(screen.getByText(/Đã chọn 10 nguồn đầu tiên theo thứ tự trong kho/)).toBeInTheDocument();
    const eleventh = screen.getByRole('checkbox', { name: 'Chọn nguồn Capacity source 11 cho bản nháp' });
    expect(eleventh).not.toBeChecked();
    expect(eleventh).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Chọn nguồn Capacity source 1 cho bản nháp' }));
    expect(eleventh).toBeEnabled();
    fireEvent.click(eleventh);
    expect(eleventh).toBeChecked();
    expect(screen.getByText('10 / 10 nguồn đã chọn')).toBeInTheDocument();
  });

  it('keeps unreadable sources in the library but disables and excludes them from Draft', async () => {
    mocks.getTopicSources.mockResolvedValue(capacityTopicLibrary(3, [2]));
    await renderReadyPage();
    await chooseContext();
    await screen.findByText('3 tài liệu đã lưu');

    const unreadable = screen.getByRole('checkbox', { name: 'Chọn nguồn Capacity source 2 cho bản nháp' });
    expect(unreadable).toBeDisabled();
    expect(screen.getByText('AI chưa có nội dung để đọc')).toBeInTheDocument();
    expect(screen.getByText('Nguồn vẫn được lưu trong kho để tham khảo.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả nguồn AI đọc được' }));

    expect(screen.getByText('2 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByText('Tạo bản nháp bằng AI từ 2 nguồn')).toBeInTheDocument();
    const basket = screen.getByRole('heading', { name: 'Nguồn sẽ dùng cho bản nháp' }).closest('section')!;
    expect(within(basket).queryByText('Capacity source 2')).not.toBeInTheDocument();
    expect(within(basket).getByText('Capacity source 1')).toBeInTheDocument();
    expect(within(basket).getByText('Capacity source 3')).toBeInTheDocument();
  });

  it('removes a stale selected source when refreshed evidence is no longer readable', async () => {
    mocks.getTopicSources
      .mockResolvedValueOnce(capacityTopicLibrary(1))
      .mockResolvedValue(capacityTopicLibrary(1, [1]));
    await renderReadyPage();
    await chooseContext();
    const sourceCheckbox = await screen.findByRole('checkbox', {
      name: 'Chọn nguồn Capacity source 1 cho bản nháp',
    });
    fireEvent.click(sourceCheckbox);
    expect(screen.getByText('1 / 10 nguồn đã chọn')).toBeInTheDocument();

    switchToFreeSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    await screen.findByRole('heading', { name: /Tìm thấy 2 tài liệu/ });
    fireEvent.click(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 tài liệu vào kho chủ đề' }));

    expect(await screen.findByText(/1 nguồn đã được bỏ khỏi bản nháp/)).toBeInTheDocument();
    expect(screen.getByText('0 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Chọn nguồn Capacity source 1 cho bản nháp' })).toBeDisabled();
  });

  it('makes a re-enriched source selectable without auto-selecting it for Draft', async () => {
    mocks.getTopicSources
      .mockResolvedValueOnce(capacityTopicLibrary(1, [1]))
      .mockResolvedValue(capacityTopicLibrary(1));
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByRole('checkbox', {
      name: 'Chọn nguồn Capacity source 1 cho bản nháp',
    })).toBeDisabled();

    switchToFreeSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    await screen.findByRole('heading', { name: /Tìm thấy 2 tài liệu/ });
    fireEvent.click(screen.getByRole('checkbox', { name: /Rainfall and pediatric/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 tài liệu vào kho chủ đề' }));

    const refreshed = await screen.findByRole('checkbox', {
      name: 'Chọn nguồn Capacity source 1 cho bản nháp',
    });
    expect(refreshed).toBeEnabled();
    expect(refreshed).not.toBeChecked();
    expect(screen.getByText('0 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
  });

  it('keeps Draft selection stable while another keyword search runs', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu PubMed' }));
    await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('checkbox', { name: /Rainfall.*cho bản nháp/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Record without abstract.*cho bản nháp/ })).toBeChecked();
    expect(screen.getByText('Tạo bản nháp bằng AI từ 2 nguồn')).toBeInTheDocument();
  });

  it('previews exact Draft sources, removes one, and sends only the remaining ID', async () => {
    await importAllSources();
    expect(screen.getByRole('heading', { name: 'Nguồn sẽ dùng cho bản nháp' })).toBeInTheDocument();
    expect(screen.getAllByText('PMID: 12345678').length).toBeGreaterThan(0);
    expect(screen.getAllByText('PMID: 87654321').length).toBeGreaterThan(0);
    expect(screen.getByText('Tạo bản nháp bằng AI từ 2 nguồn')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Bỏ nguồn 87654321' }));
    expect(screen.getByText('Tạo bản nháp bằng AI từ 1 nguồn')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await waitFor(() => expect(mocks.generateDraft).toHaveBeenCalledWith({
      disease_group_id: '5',
      factor_type: 'WEATHER',
      factor_key: 'precipitation',
      factor_value: null,
      weather_factor: 'precipitation',
      source_ids: [10],
    }));
  });

  it('clears Pneumonia-topic Draft selection when switching to Influenza', async () => {
    await importAllSources();
    mocks.getTopicSources.mockResolvedValue({
      topic_id: null,
      disease_group_id: '168',
      weather_factor: 'precipitation',
      sources: [],
    });
    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '168' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('168', weatherSelector('precipitation')));
    expect(screen.getByText('0 tài liệu')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
    expect(screen.queryByText('PMID: 12345678')).not.toBeInTheDocument();
  });

  it('ignores a stale keyword response after the topic changes', async () => {
    let resolveSearch!: (value: ReviewedProviderSearchResponse) => void;
    mocks.searchProviders.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve; }));
    await renderReadyPage();
    await chooseContext();
    addTerm();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '168' } });
    resolveSearch(singleProviderResponse(multiProviderSearchResponse.providers[0]));
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('168', weatherSelector('precipitation')));
    expect(screen.queryByText('Rainfall and pediatric gastroenteritis')).not.toBeInTheDocument();
  });

  it('clears stale results and disease terms when disease group changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '1' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('1', weatherSelector('precipitation')));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    expect(screen.queryByText('gastroenteritis')).not.toBeInTheDocument();
  });

  it('clears stale results but keeps disease terms when weather factor changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('2. Yếu tố cần giải thích'), { target: { value: 'WEATHER:humidity' } });
    await waitFor(() => expect(mocks.getHistory).toHaveBeenCalledWith('5', weatherSelector('humidity')));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm có hướng dẫn' }));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
  });

  it('keeps generated query collapsed before sources are imported', async () => {
    await runSuccessfulSearch();
    const details = screen.getByText('Chi tiết tìm kiếm').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
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
    expect(screen.getByRole('button', { name: 'Tìm tài liệu' })).toBeEnabled();
  });

  it('shows generation loading wording and prevents double submit', async () => {
    mocks.generateDraft.mockReturnValue(new Promise(() => undefined));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' })).toBeDisabled();
    expect(screen.getByText('Đang tạo bản nháp…')).toBeInTheDocument();
    expect(screen.getByText(/AI đang đọc evidence content đã lưu/)).toBeInTheDocument();
    expect(mocks.generateDraft).toHaveBeenCalledTimes(1);
  });

  it('maps generation provider errors without exposing raw details', async () => {
    mocks.generateDraft.mockRejectedValue(new ApiError(502, 'raw provider payload'));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AI chưa thể tạo bản nháp hợp lệ');
    expect(screen.queryByText('raw provider payload')).not.toBeInTheDocument();
  });

  it.each([
    ['DRAFT_NO_SOURCES_SELECTED', 'Bạn chưa chọn tài liệu nào cho bản nháp.'],
    ['DRAFT_TOO_MANY_SOURCES', 'Một bản nháp hiện hỗ trợ tối đa 10 nguồn.'],
    ['DRAFT_SOURCE_NO_USABLE_EVIDENCE', 'Một hoặc nhiều tài liệu đã chọn chưa có nội dung mà AI có thể đọc.'],
    ['DRAFT_SCOPE_WHOLE_GROUP_REQUIRES_DIRECT', 'AI đề xuất phạm vi áp dụng cho toàn nhóm bệnh, nhưng các nguồn hiện tại chưa có ít nhất một nguồn trực tiếp phù hợp. Bản nháp chưa được lưu.'],
    ['DRAFT_SUPPORTED_REQUIRES_PEDIATRIC_SOURCE', 'AI đề xuất SUPPORTED nhưng chưa có cùng một nguồn vừa hỗ trợ trực tiếp quan hệ bệnh–thời tiết vừa nghiên cứu trực tiếp trên trẻ em. Bản nháp chưa được lưu.'],
    ['DRAFT_PROPOSAL_INVALID', 'AI trả về bản đề xuất chưa đáp ứng quy tắc kiểm tra. Vui lòng xem lại nguồn hoặc thử tạo lại.'],
  ])('shows the specific %s Draft error', async (code, message) => {
    mocks.generateDraft.mockRejectedValue(new ApiError(422, 'safe domain detail', code));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText('Nguồn hoặc phạm vi tạo bản nháp chưa hợp lệ.')).not.toBeInTheDocument();
  });

  it('clears the selected basket on a cross-topic backend rejection', async () => {
    mocks.generateDraft.mockRejectedValue(new ApiError(
      422,
      'source belongs to another topic',
      'DRAFT_SOURCE_NOT_IN_TOPIC',
    ));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Một hoặc nhiều tài liệu đã chọn không thuộc kho nguồn của chủ đề hiện tại. Danh sách chọn đã được làm mới.',
    );
    expect(screen.getByText('0 tài liệu')).toBeInTheDocument();
  });

  it('uses the safe generic Draft error only for an unknown 422 code', async () => {
    mocks.generateDraft.mockRejectedValue(new ApiError(422, 'private detail', 'UNKNOWN_VALIDATION'));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Yêu cầu tạo bản nháp chưa hợp lệ. Vui lòng tải lại kho nguồn và kiểm tra lựa chọn.',
    );
    expect(screen.queryByText('private detail')).not.toBeInTheDocument();
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
    expect(screen.getByText('Đúng đối tượng trẻ em')).toBeInTheDocument();
    expect(screen.getByText('Abstract mô tả trực tiếp trẻ em.')).toBeInTheDocument();
    expect(screen.getByText('Đủ điều kiện nội dung Tier 2 cho phụ huynh')).toBeInTheDocument();
    expect(screen.queryByText(/chưa có nguồn PEDIATRIC_DIRECT/)).not.toBeInTheDocument();
    expect(screen.getAllByText('AI sử dụng: Trích đoạn toàn văn PMC').length).toBeGreaterThan(0);
    expect(screen.getAllByText('PMC123456').length).toBeGreaterThan(0);
  });

  it.each([
    ['MIXED_AGE', 'Nghiên cứu nhiều độ tuổi'],
    ['ADULT_ONLY', 'Chỉ người lớn'],
    ['ELDERLY_ONLY', 'Chỉ người cao tuổi'],
    ['UNKNOWN', 'Chưa xác định đối tượng'],
  ] as const)('renders %s and warns staff when pediatric-direct support is absent', async (
    populationRelevance,
    populationLabel,
  ) => {
    const nonPediatricRevision: DraftRevision = {
      ...draftRevision,
      sources: draftRevision.sources.map((source) => ({
        ...source,
        population_relevance: populationRelevance,
        population_note: `Assessment nhóm tuổi: ${populationRelevance}.`,
      })),
      parent_tier2_eligible: false,
      parent_tier2_ineligibility_reasons: ['PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED'],
    };
    mocks.generateDraft.mockResolvedValue(nonPediatricRevision);
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));

    expect(await screen.findByText(populationLabel)).toBeInTheDocument();
    expect(screen.getByText(`Assessment nhóm tuổi: ${populationRelevance}.`)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('chưa có nguồn PEDIATRIC_DIRECT');
    expect(screen.getByText('Chưa đủ điều kiện nội dung Tier 2 cho phụ huynh')).toBeInTheDocument();
    expect(screen.getByText(/Thiếu nguồn vừa hỗ trợ trực tiếp/)).toBeInTheDocument();
  });

  it('loads a historical source with missing population fields as UNKNOWN without crashing', async () => {
    const legacyRevision: DraftRevision = {
      ...draftRevision,
      sources: draftRevision.sources.map((source) => {
        const { population_relevance: _population, population_note: _note, ...legacySource } = source;
        return legacySource;
      }),
      parent_tier2_eligible: false,
      parent_tier2_ineligibility_reasons: ['PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED'],
    };
    mocks.generateDraft.mockResolvedValue(legacyRevision);
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));

    expect(await screen.findByText('Chưa xác định đối tượng')).toBeInTheDocument();
    expect(screen.getByText(/chưa lưu đánh giá nhóm tuổi \(UNKNOWN\)/)).toBeInTheDocument();
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

  it('shows Save and Approve actions for an authorized DRAFT', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Duyệt bản này' })).toBeInTheDocument();
  });

  it('requires approval confirmation and explicitly warns that Parent cannot see it', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.click(screen.getByRole('button', { name: 'Duyệt bản này' }));

    const dialog = screen.getByRole('dialog', { name: 'Xác nhận duyệt phiên bản' });
    expect(within(dialog).getByText(/đã kiểm tra nội dung và nguồn/)).toBeInTheDocument();
    expect(within(dialog).getByText(/CHƯA được xuất bản cho phụ huynh/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mocks.approveRevision).not.toHaveBeenCalled();
  });

  it('shows approval loading and prevents another approval action', async () => {
    mocks.approveRevision.mockReturnValue(new Promise(() => undefined));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.click(screen.getByRole('button', { name: 'Duyệt bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận duyệt' }));

    expect(screen.getByRole('button', { name: 'Đang duyệt…' })).toBeDisabled();
    expect(mocks.approveRevision).toHaveBeenCalledTimes(1);
  });

  it('updates to immutable APPROVED UI with reviewer and time after approval', async () => {
    mocks.getRevision.mockResolvedValue(approvedRevision);
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.click(screen.getByRole('button', { name: 'Duyệt bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận duyệt' }));

    expect(await screen.findByText('APPROVED — Đã duyệt')).toBeInTheDocument();
    expect(screen.getByText('Bác sĩ kiểm duyệt')).toBeInTheDocument();
    expect(screen.getByText(/23\/8\/26/)).toBeInTheDocument();
    expect(screen.getByText(/đã được duyệt và đang được khóa/)).toBeInTheDocument();
    expect(screen.getByText(/vẫn chưa được xuất bản cho phụ huynh/)).toBeInTheDocument();
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Lưu bản nháp' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Duyệt bản này' })).not.toBeInTheDocument();
    expect(mocks.approveRevision).toHaveBeenCalledWith(21);
  });

  it('maps approval authorization failures without exposing backend detail', async () => {
    mocks.approveRevision.mockRejectedValue(new ApiError(403, 'private authorization detail'));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.click(screen.getByRole('button', { name: 'Duyệt bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận duyệt' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Bạn không có quyền duyệt phiên bản này.');
    expect(screen.queryByText('private authorization detail')).not.toBeInTheDocument();
  });

  it('shows the actionable pediatric-support approval error', async () => {
    mocks.approveRevision.mockRejectedValue(new ApiError(
      422,
      'safe pediatric domain detail',
      'APPROVAL_PEDIATRIC_SUPPORT_REQUIRED',
    ));
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    fireEvent.click(screen.getByRole('button', { name: 'Duyệt bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận duyệt' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Không thể duyệt mức SUPPORTED: cần ít nhất một nguồn vừa hỗ trợ trực tiếp quan hệ bệnh–thời tiết vừa nghiên cứu trực tiếp trên trẻ em.',
    );
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
    expect(mocks.getHistory).toHaveBeenCalledWith('5', weatherSelector('precipitation'));
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
    expect(
      await screen.findByText(status === 'APPROVED' ? 'APPROVED — Đã duyệt' : 'REJECTED — Chỉ đọc'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: 'Lưu bản nháp' })).not.toBeInTheDocument();
  });

  it('does not expose any Publish action', async () => {
    await importAllSources();
    fireEvent.click(screen.getByRole('button', { name: 'Tạo bản nháp bằng AI' }));
    await screen.findByRole('heading', { name: 'Revision 2' });
    expect(screen.queryByRole('button', { name: /publish|xuất bản/i })).not.toBeInTheDocument();
  });

  it.each(['admin', 'staff'])('shows Publish only for an authorized APPROVED revision (%s)', async (role) => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [approvedRevision],
    });
    mocks.getRevision.mockResolvedValue(approvedRevision);
    await renderReadyPage(role);
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    expect(await screen.findByRole('button', { name: 'Xuất bản bản này' })).toBeInTheDocument();
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveAttribute('readonly');
  });

  it('requires publication confirmation and cancel has no side effect', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [approvedRevision],
    });
    mocks.getRevision.mockResolvedValue(approvedRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Xuất bản bản này' }));

    const dialog = screen.getByRole('dialog', { name: 'Xác nhận xuất bản phiên bản' });
    expect(within(dialog).getByText(/bản kiến thức chính thức/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Nội dung đã duyệt sẽ không bị thay đổi/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }));
    expect(screen.queryByRole('dialog', { name: 'Xác nhận xuất bản phiên bản' })).not.toBeInTheDocument();
    expect(mocks.publishRevision).not.toHaveBeenCalled();
  });

  it('warns before replacing an existing current publication', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 20,
      },
      revisions: [approvedRevision],
    });
    mocks.getRevision.mockResolvedValue(approvedRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Xuất bản bản này' }));
    expect(screen.getByText(/Phiên bản đang xuất bản hiện tại sẽ được thay thế/)).toBeInTheDocument();
    expect(screen.getByText(/Phiên bản cũ vẫn được giữ trong lịch sử/)).toBeInTheDocument();
  });

  it('shows publication loading state and prevents another action', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [approvedRevision],
    });
    mocks.getRevision.mockResolvedValue(approvedRevision);
    mocks.publishRevision.mockReturnValue(new Promise(() => undefined));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Xuất bản bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận xuất bản' }));
    expect(screen.getByRole('button', { name: 'Đang xuất bản…' })).toBeDisabled();
    expect(mocks.publishRevision).toHaveBeenCalledTimes(1);
  });

  it('reloads revision and topic then renders current publication audit', async () => {
    mocks.getHistory
      .mockResolvedValueOnce({
        topic: {
          id: 7,
          disease_group_id: '5',
          disease_group_name: draftRevision.disease_group_name,
          weather_factor: 'precipitation',
          published_revision_id: null,
        },
        revisions: [approvedRevision],
      })
      .mockResolvedValue({
        topic: {
          id: 7,
          disease_group_id: '5',
          disease_group_name: draftRevision.disease_group_name,
          weather_factor: 'precipitation',
          published_revision_id: 21,
        },
        revisions: [publishedRevision],
      });
    mocks.getRevision
      .mockResolvedValueOnce(approvedRevision)
      .mockResolvedValueOnce(publishedRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Xuất bản bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận xuất bản' }));

    expect(await screen.findByText('ĐANG XUẤT BẢN')).toBeInTheDocument();
    expect(screen.getByText('Điều phối xuất bản')).toBeInTheDocument();
    expect(screen.getByText(/Xuất bản bởi/)).toHaveTextContent('10:00 23/8/26');
    expect(screen.queryByRole('button', { name: 'Xuất bản bản này' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Giải thích ngắn')).toHaveAttribute('readonly');
    expect(mocks.publishRevision).toHaveBeenCalledWith(21);
    expect(mocks.getRevision).toHaveBeenCalledTimes(2);
    expect(mocks.getHistory.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('shows a safe publication authorization error', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [approvedRevision],
    });
    mocks.getRevision.mockResolvedValue(approvedRevision);
    mocks.publishRevision.mockRejectedValue(new ApiError(403, 'private publication detail'));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Xuất bản bản này' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận xuất bản' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Bạn không có quyền xuất bản phiên bản này.');
    expect(screen.queryByText('private publication detail')).not.toBeInTheDocument();
  });

  it('marks only the current pointer as published after replacement', async () => {
    const oldApproved = { ...approvedRevision, id: 20, revision_number: 1, is_published: false };
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 21,
      },
      revisions: [publishedRevision, oldApproved],
    });
    mocks.getRevision.mockResolvedValue(oldApproved);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 1 — APPROVED' }));
    expect(await screen.findByText('APPROVED — Đã duyệt')).toBeInTheDocument();
    expect(screen.queryByText('ĐANG XUẤT BẢN')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Xuất bản bản này' })).toBeInTheDocument();
  });

  it('does not show Unpublish for DRAFT or APPROVED-but-unpublished revisions', async () => {
    const firstDraftRevision = {
      ...draftRevision,
      id: 20,
      revision_number: 1,
    };
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: null,
      },
      revisions: [firstDraftRevision, approvedRevision],
    });
    mocks.getRevision.mockResolvedValueOnce(firstDraftRevision).mockResolvedValueOnce(approvedRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 1 — DRAFT' }));
    expect(await screen.findByText('DRAFT — Chưa xuất bản')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ngừng xuất bản' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Revision 2 — APPROVED' }));
    expect(await screen.findByRole('button', { name: 'Xuất bản bản này' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ngừng xuất bản' })).not.toBeInTheDocument();
  });

  it.each(['admin', 'staff'])('shows Unpublish only for an authorized current publication (%s)', async (role) => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 21,
      },
      revisions: [publishedRevision],
    });
    mocks.getRevision.mockResolvedValue(publishedRevision);
    await renderReadyPage(role);
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    expect(await screen.findByRole('button', { name: 'Ngừng xuất bản' })).toBeInTheDocument();
    expect(screen.getByText('ĐANG XUẤT BẢN')).toBeInTheDocument();
  });

  it('requires clear Unpublish confirmation and cancel has no side effect', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 21,
      },
      revisions: [publishedRevision],
    });
    mocks.getRevision.mockResolvedValue(publishedRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Ngừng xuất bản' }));

    const dialog = screen.getByRole('dialog', { name: 'Xác nhận ngừng xuất bản phiên bản' });
    expect(within(dialog).getByText('Phụ huynh sẽ không còn thấy phần giải thích y khoa này.')).toBeInTheDocument();
    expect(within(dialog).getByText(/vẫn được giữ ở trạng thái Đã duyệt và không bị xóa/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Hủy' }));
    expect(screen.queryByRole('dialog', { name: 'Xác nhận ngừng xuất bản phiên bản' })).not.toBeInTheDocument();
    expect(mocks.unpublishRevision).not.toHaveBeenCalled();
  });

  it('shows Unpublish loading state and prevents another action', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 21,
      },
      revisions: [publishedRevision],
    });
    mocks.getRevision.mockResolvedValue(publishedRevision);
    mocks.unpublishRevision.mockReturnValue(new Promise(() => undefined));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Ngừng xuất bản' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận ngừng xuất bản' }));
    expect(screen.getByRole('button', { name: 'Đang ngừng xuất bản…' })).toBeDisabled();
    expect(mocks.unpublishRevision).toHaveBeenCalledTimes(1);
  });

  it('removes the current badge but keeps APPROVED read-only content and enables Publish again', async () => {
    const withdrawnRevision = {
      ...approvedRevision,
      is_published: false,
      parent_display_allowed: false,
      published_by: null,
      published_by_name: null,
      published_at: null,
    };
    mocks.getHistory
      .mockResolvedValueOnce({
        topic: {
          id: 7,
          disease_group_id: '5',
          disease_group_name: draftRevision.disease_group_name,
          weather_factor: 'precipitation',
          published_revision_id: 21,
        },
        revisions: [publishedRevision],
      })
      .mockResolvedValue({
        topic: {
          id: 7,
          disease_group_id: '5',
          disease_group_name: draftRevision.disease_group_name,
          weather_factor: 'precipitation',
          published_revision_id: null,
        },
        revisions: [withdrawnRevision],
      });
    mocks.getRevision
      .mockResolvedValueOnce(publishedRevision)
      .mockResolvedValueOnce(withdrawnRevision);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    const originalShort = (await screen.findByLabelText('Giải thích ngắn') as HTMLTextAreaElement).value;
    fireEvent.click(screen.getByRole('button', { name: 'Ngừng xuất bản' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận ngừng xuất bản' }));

    expect(await screen.findByText(/Đã ngừng xuất bản phiên bản/)).toBeInTheDocument();
    expect(screen.queryByText('ĐANG XUẤT BẢN')).not.toBeInTheDocument();
    expect(screen.getByText('APPROVED — Đã duyệt')).toBeInTheDocument();
    const withdrawnShortExplanation = await screen.findByLabelText('Giải thích ngắn');
    expect(withdrawnShortExplanation).toHaveAttribute('readonly');
    expect(withdrawnShortExplanation).toHaveValue(originalShort);
    expect(screen.getByRole('button', { name: 'Xuất bản bản này' })).toBeInTheDocument();
    expect(mocks.unpublishRevision).toHaveBeenCalledWith(21);
  });

  it('shows a safe Unpublish authorization error without leaking backend details', async () => {
    mocks.getHistory.mockResolvedValue({
      topic: {
        id: 7,
        disease_group_id: '5',
        disease_group_name: draftRevision.disease_group_name,
        weather_factor: 'precipitation',
        published_revision_id: 21,
      },
      revisions: [publishedRevision],
    });
    mocks.getRevision.mockResolvedValue(publishedRevision);
    mocks.unpublishRevision.mockRejectedValue(new ApiError(403, 'private unpublish detail'));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('button', { name: 'Revision 2 — APPROVED' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Ngừng xuất bản' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận ngừng xuất bản' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Bạn không có quyền ngừng xuất bản phiên bản này.');
    expect(screen.queryByText('private unpublish detail')).not.toBeInTheDocument();
  });

  it('Reviewed provider selector exposes only globally enabled providers', async () => {
    await renderReadyPage('staff');
    expect(await screen.findByRole('checkbox', { name: 'PubMed / PMC' })).toBeInTheDocument();
    expect(screen.queryByText('World Health Organization (WHO)')).not.toBeInTheDocument();
  });

  it('routes a WHO-only Guided search to exactly one WHO provider group', async () => {
    enableWhoReviewed();
    const who = multiProviderSearchResponse.providers[1];
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(who));
    await selectWhoOnlyAndSearch();

    expect(mocks.searchProviders).toHaveBeenCalledWith(expect.objectContaining({ provider_ids: ['WHO'] }));
    expect(mocks.search).not.toHaveBeenCalled();
    expect(within(screen.getByRole('tablist', { name: 'Kết quả theo nguồn' })).getAllByRole('tab')).toHaveLength(1);
    expect(screen.getByRole('tab', { name: /World Health Organization.*1 kết quả phù hợp/ })).toBeVisible();
    expect(screen.queryByRole('tab', { name: /PubMed/ })).not.toBeInTheDocument();
  });

  it('routes PubMed-only Guided search through provider orchestration when WHO is enabled', async () => {
    enableWhoReviewed();
    const pubmed = multiProviderSearchResponse.providers[0];
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(pubmed));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await screen.findByRole('heading', { name: 'Kết quả theo nguồn' });

    expect(mocks.searchProviders).toHaveBeenCalledWith(expect.objectContaining({ provider_ids: ['PUBMED'] }));
    expect(mocks.search).not.toHaveBeenCalled();
    expect(within(screen.getByRole('tablist', { name: 'Kết quả theo nguồn' })).getAllByRole('tab')).toHaveLength(1);
  });

  it('routes PubMed-only Guided search through shared relevance when PubMed is the only enabled provider', async () => {
    const pubmed = multiProviderSearchResponse.providers[0];
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(pubmed));
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await screen.findByRole('heading', { name: 'Kết quả theo nguồn' });

    expect(mocks.searchProviders).toHaveBeenCalledWith(expect.objectContaining({ provider_ids: ['PUBMED'] }));
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('renders only final accepted relevance and never promotes query provenance', async () => {
    const template = multiProviderSearchResponse.results[0];
    const direct = {
      ...template,
      external_id: 'plague-humidity',
      title: 'Plague transmission and relative humidity',
      relevance: 'DIRECT_TOPIC' as const,
      query_level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC',
    };
    const related = {
      ...template,
      external_id: 'plague-vaccination',
      title: 'Plague vaccination',
      relevance: 'RELATED_CONTEXT' as const,
      query_level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC',
    };
    const rejected = [
      {
        ...template,
        external_id: 'wrong-mpro',
        title: 'The temperature-dependent conformational ensemble of SARS-CoV-2 main protease (Mpro).',
        relevance: 'REJECT' as const,
        query_level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC',
      },
      {
        ...template,
        external_id: 'wrong-agriculture',
        title: 'Edge IoT Prototyping Using Model-Driven Representations: A Use Case for Smart Agriculture.',
        relevance: 'REJECT' as const,
        query_level: 'DIRECT_DISEASE_FACTOR_PEDIATRIC',
      },
    ];
    const group = {
      ...multiProviderSearchResponse.providers[0],
      returned_count: 2,
      direct_count: 1,
      related_count: 1,
      relevant_count: 2,
      rejected_count: 2,
      results: [...rejected, direct, related],
    };
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(group));

    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await screen.findByText(direct.title);

    expect(screen.queryByText(rejected[0].title)).not.toBeInTheDocument();
    expect(screen.queryByText(rejected[1].title)).not.toBeInTheDocument();
    expect(within(screen.getByText(direct.title).closest('label')!).getByText('Bằng chứng trực tiếp')).toBeVisible();
    expect(within(screen.getByText(related.title).closest('label')!).getByText('Tài liệu liên quan')).toBeVisible();
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('clears old provider groups immediately and replaces them with the next search response', async () => {
    const first = multiProviderSearchResponse.results[0];
    const second = { ...first, external_id: 'new-result', title: 'New plague humidity evidence' };
    const firstGroup = { ...multiProviderSearchResponse.providers[0], results: [first] };
    const secondGroup = { ...multiProviderSearchResponse.providers[0], results: [second] };
    let resolveSecond!: (value: ReviewedProviderSearchResponse) => void;
    mocks.searchProviders
      .mockResolvedValueOnce(singleProviderResponse(firstGroup))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));

    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    expect(await screen.findByText(first.title)).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    expect(screen.queryByText(first.title)).not.toBeInTheDocument();
    resolveSecond(singleProviderResponse(secondGroup));
    expect(await screen.findByText(second.title)).toBeVisible();
    expect(screen.queryByText(first.title)).not.toBeInTheDocument();
  });

  it('shows WHO successful zero relevance as NO_RESULTS with execution diagnostics', async () => {
    enableWhoReviewed();
    const who = {
      ...multiProviderSearchResponse.providers[1],
      returned_count: 0,
      total_available: 10,
      provider_total_available: 10,
      raw_result_count: 10,
      raw_candidates_examined: 10,
      pages_fetched: 1,
      provider_exhausted: true,
      stop_reason: 'PROVIDER_EXHAUSTED' as const,
      normalized_count: 10,
      normalized_candidates: 10,
      disease_match_count: 0,
      factor_match_count: 2,
      relevant_count: 0,
      direct_count: 0,
      related_count: 0,
      rejected_count: 10,
      status: 'NO_RESULTS' as const,
      results: [],
      query_attempts: [{
        ...multiProviderSearchResponse.providers[1].query_attempts[0],
        provider_match_count: 10,
        fetched_count: 10,
        normalized_count: 10,
        disease_match_count: 0,
        factor_match_count: 2,
        relevant_count: 0,
        direct_count: 0,
        related_count: 0,
        rejected_count: 10,
      }],
    };
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(who));
    await selectWhoOnlyAndSearch();

    expect(screen.getByRole('tab', { name: /0 kết quả phù hợp/ })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Đã kiểm tra 10 kết quả WHO nhưng chưa tìm thấy tài liệu đồng thời phù hợp với bệnh và yếu tố.');
    fireEvent.click(screen.getByText('Chi tiết kỹ thuật tìm kiếm'));
    expect(screen.getByText(/Đã gọi: có.*Trạng thái provider: SUCCESS/)).toBeVisible();
    expect(screen.getByText(/đã kiểm tra 10.*trực tiếp 0.*liên quan 0.*loại 10.*trả về 0/)).toBeVisible();
  });

  it('shows when WHO stopped at the safe candidate budget', async () => {
    enableWhoReviewed();
    const who = {
      ...multiProviderSearchResponse.providers[1],
      returned_count: 0,
      total_available: 294,
      provider_total_available: 294,
      raw_result_count: 40,
      raw_candidates_examined: 40,
      normalized_count: 40,
      normalized_candidates: 40,
      disease_match_count: 2,
      factor_match_count: 3,
      relevant_count: 0,
      pages_fetched: 4,
      budget_exhausted: true,
      provider_exhausted: false,
      stop_reason: 'CANDIDATE_BUDGET_REACHED' as const,
      direct_count: 0,
      related_count: 0,
      rejected_count: 40,
      status: 'NO_RESULTS' as const,
      results: [],
    };
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(who));
    await selectWhoOnlyAndSearch();

    fireEvent.click(screen.getByText('Chi tiết kỹ thuật tìm kiếm'));
    expect(screen.getByText(/tổng từ nhà cung cấp 294.*số trang 4.*đã kiểm tra 40/)).toBeVisible();
    expect(screen.getByText('Đã dừng khi đạt ngân sách ứng viên an toàn.')).toBeVisible();
  });

  it('shows WHO timeout as PROVIDER_ERROR and exposes only its safe code', async () => {
    enableWhoReviewed();
    const warning = { provider_id: 'WHO', code: 'WHO_SEARCH_TIMEOUT', message: 'safe message' };
    const who = {
      ...multiProviderSearchResponse.providers[1],
      returned_count: 0,
      total_available: null,
      provider_status: 'PROVIDER_ERROR' as const,
      raw_result_count: 0,
      normalized_count: 0,
      disease_match_count: 0,
      factor_match_count: 0,
      relevant_count: 0,
      direct_count: 0,
      status: 'PROVIDER_ERROR' as const,
      warning,
      results: [],
      query_attempts: [{
        ...multiProviderSearchResponse.providers[1].query_attempts[0],
        provider_match_count: 0,
        fetched_count: 0,
        normalized_count: 0,
        disease_match_count: 0,
        factor_match_count: 0,
        relevant_count: 0,
        status: 'PROVIDER_ERROR' as const,
        warning,
      }],
    };
    mocks.searchProviders.mockResolvedValue(singleProviderResponse(who));
    await selectWhoOnlyAndSearch();

    expect(screen.getByRole('tab', { name: /Tạm thời không khả dụng/ })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Tạm thời không khả dụng');
    expect(screen.queryByText(/0 kết quả phù hợp/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Chi tiết kỹ thuật tìm kiếm'));
    expect(screen.getByText(/Trạng thái provider: PROVIDER_ERROR/)).toBeVisible();
    expect(screen.getAllByText('WHO_SEARCH_TIMEOUT')).toHaveLength(2);
    expect(screen.queryByText('fixture timeout')).not.toBeInTheDocument();
  });

  it('renders backend provider groups with independent result counts', async () => {
    await runMultiProviderSearch();
    expect(screen.getByRole('tab', { name: /PubMed \/ PMC.*1 kết quả/ })).toBeVisible();
    expect(screen.getByRole('tab', { name: /World Health Organization \(WHO\).*1 kết quả/ })).toBeVisible();
    expect(screen.getByText('2 kết quả · 2 bằng chứng duy nhất')).toBeVisible();
  });

  it('renders and orders direct before related evidence with distinct badges', async () => {
    const direct = multiProviderSearchResponse.results[0];
    const contextual = {
      ...direct,
      external_id: 'context-1',
      title: 'Pediatric plague background without factor evidence',
      relevance: 'RELATED_CONTEXT' as const,
      query_level: 'RELATED_DISEASE_PEDIATRIC',
    };
    enableWhoReviewed();
    mocks.searchProviders.mockResolvedValue({
      ...multiProviderSearchResponse,
      count: 2,
      unique_count: 2,
      results: [direct, contextual],
      providers: [{
        ...multiProviderSearchResponse.providers[0],
        returned_count: 2,
        relevant_count: 2,
        direct_count: 1,
        related_count: 1,
        contextual_count: 1,
        results: [direct, contextual],
      }],
    });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));

    expect(await screen.findByText('Yêu cầu 10 · 1 trực tiếp · 1 liên quan')).toBeVisible();
    const directBadge = screen.getByText('Bằng chứng trực tiếp');
    const relatedBadge = screen.getByText('Tài liệu liên quan');
    expect(directBadge.compareDocumentPosition(relatedBadge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Smart agriculture humidity sensors')).not.toBeInTheDocument();
  });

  it('shows post-filter provider diagnostics only in technical details', async () => {
    enableWhoReviewed();
    mocks.searchProviders.mockResolvedValue({
      ...multiProviderSearchResponse,
      providers: multiProviderSearchResponse.providers.map((group) => group.provider_id === 'WHO' ? {
        ...group,
        raw_result_count: 10,
        raw_candidates_examined: 10,
        normalized_count: 10,
        normalized_candidates: 10,
        relevant_count: 1,
        direct_count: 1,
        related_count: 0,
        rejected_count: 9,
      } : group),
    });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    fireEvent.click(await screen.findByRole('tab', { name: /World Health Organization/ }));
    fireEvent.click(screen.getByText('Chi tiết kỹ thuật tìm kiếm'));
    expect(screen.getByText(/đã kiểm tra 10.*chuẩn hóa 10.*trực tiếp 1.*liên quan 0.*loại 9.*trả về 1/)).toBeVisible();
  });

  it('switches provider tabs without mixing their result cards', async () => {
    await runMultiProviderSearch();
    const pubmedPanel = screen.getByRole('tabpanel', { name: /PubMed \/ PMC/ });
    expect(within(pubmedPanel).getByText('PubMed mixed evidence')).toBeVisible();
    expect(within(pubmedPanel).queryByText('WHO influenza metadata record')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /World Health Organization \(WHO\)/ }));
    const whoPanel = await screen.findByRole('tabpanel', { name: /World Health Organization/ });
    expect(within(whoPanel).getByText('WHO influenza metadata record')).toBeVisible();
    expect(within(whoPanel).queryByText('PubMed mixed evidence')).not.toBeInTheDocument();
  });

  it('preserves provider selections across tab changes and reports per-group counts', async () => {
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('PubMed mixed evidence'));
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    expect(await screen.findByText('Đã chọn 2 tài liệu')).toBeVisible();
    expect(screen.getByRole('tab', { name: /WHO.*1 đã chọn/ })).toBeVisible();

    const pubmed = await providerResultCheckbox('PubMed mixed evidence');
    expect(pubmed).toBeChecked();
    expect(screen.getByRole('tab', { name: /PubMed \/ PMC.*1 đã chọn/ })).toBeVisible();
  });

  it('selects all only inside the active provider group', async () => {
    await runMultiProviderSearch();
    fireEvent.click(screen.getByRole('button', { name: 'Chọn tất cả trong PubMed / PMC' }));
    expect(await screen.findByText('Đã chọn 1 tài liệu')).toBeVisible();
    const who = await providerResultCheckbox('WHO influenza metadata record');
    expect(who).not.toBeChecked();
    expect(screen.getByRole('tab', { name: /PubMed \/ PMC.*1 đã chọn/ })).toBeVisible();
  });

  it('runs an enabled PubMed plus WHO Reviewed search and keeps provider warnings', async () => {
    mocks.getProviderSettings.mockResolvedValue({ providers: [
      { provider_id: 'PUBMED', display_name: 'PubMed / PMC', description: 'Research', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
      { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', description: 'Official', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
    ] });
    const warning = { provider_id: 'WHO', code: 'PROVIDER_UNAVAILABLE', message: 'safe' };
    mocks.searchProviders.mockResolvedValue({
      requested_count: 10, provider_count: 2, max_candidates: 20,
      count: 0, unique_count: 0, results: [], queries: { PUBMED: 'q', WHO: 'q' },
      warnings: [warning],
      providers: [
        { provider_id: 'PUBMED', display_name: 'PubMed / PMC', requested_count: 10, effective_limit: 10, returned_count: 0, total_available: 0, provider_invoked: true, provider_status: 'SUCCESS', raw_result_count: 0, normalized_count: 0, disease_match_count: 0, factor_match_count: 0, relevant_count: 0, direct_count: 0, contextual_count: 0, status: 'NO_RESULTS', query: 'q', warning: null, query_attempts: [], results: [] },
        { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', requested_count: 10, effective_limit: 10, returned_count: 0, total_available: null, provider_invoked: true, provider_status: 'PROVIDER_ERROR', raw_result_count: 0, normalized_count: 0, disease_match_count: 0, factor_match_count: 0, relevant_count: 0, direct_count: 0, contextual_count: 0, status: 'PROVIDER_ERROR', query: 'q', warning, query_attempts: [], results: [] },
      ],
    });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));
    await waitFor(() => expect(mocks.searchProviders).toHaveBeenCalledWith(expect.objectContaining({ provider_ids: ['PUBMED', 'WHO'] })));
    fireEvent.click(await screen.findByRole('tab', { name: /World Health Organization \(WHO\)/ }));
    expect((await screen.findAllByText(/Tạm thời không khả dụng/)).length).toBeGreaterThan(0);
    expect(mocks.search).not.toHaveBeenCalled();
  });

  it('distinguishes a successful zero-result provider from a failed provider', async () => {
    mocks.getProviderSettings.mockResolvedValue({ providers: [
      { provider_id: 'PUBMED', display_name: 'PubMed / PMC', description: 'Research', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
      { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', description: 'Official', workflow: 'REVIEWED', enabled: true, capabilities: ['SEARCH'], operational_status: 'REGISTERED', updated_at: '2026-09-12T00:00:00', updated_by: null },
    ] });
    const warning = { provider_id: 'WHO', code: 'PROVIDER_UNAVAILABLE', message: 'safe' };
    mocks.searchProviders.mockResolvedValue({
      requested_count: 10, provider_count: 2, max_candidates: 20,
      count: 0, unique_count: 0, results: [], queries: { PUBMED: 'q', WHO: 'q' }, warnings: [warning],
      providers: [
        { provider_id: 'PUBMED', display_name: 'PubMed / PMC', requested_count: 10, effective_limit: 10, returned_count: 0, total_available: 0, provider_invoked: true, provider_status: 'SUCCESS', raw_result_count: 0, normalized_count: 0, disease_match_count: 0, factor_match_count: 0, relevant_count: 0, direct_count: 0, contextual_count: 0, status: 'NO_RESULTS', query: 'q', warning: null, query_attempts: [], results: [] },
        { provider_id: 'WHO', display_name: 'World Health Organization (WHO)', requested_count: 10, effective_limit: 10, returned_count: 0, total_available: null, provider_invoked: true, provider_status: 'PROVIDER_ERROR', raw_result_count: 0, normalized_count: 0, disease_match_count: 0, factor_match_count: 0, relevant_count: 0, direct_count: 0, contextual_count: 0, status: 'PROVIDER_ERROR', query: 'q', warning, query_attempts: [], results: [] },
      ],
    });
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'World Health Organization (WHO)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Tìm tài liệu' }));

    expect(await screen.findByText('Không tìm thấy tài liệu phù hợp từ nguồn này.')).toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: /World Health Organization/ }));
    expect(await screen.findByRole('status')).toHaveTextContent('Tạm thời không khả dụng');
  });

  it('selects a WHO result for library import', async () => {
    await runMultiProviderSearch();
    const who = await providerResultCheckbox('WHO influenza metadata record');
    fireEvent.click(who);
    expect(who).toBeChecked();
    expect(screen.getByRole('button', { name: 'Thêm 1 nguồn vào kho' })).toBeEnabled();
  });

  it('adds one WHO metadata result and refreshes the topic library', async () => {
    mocks.getTopicSources.mockResolvedValueOnce({
      topic_id: null, disease_group_id: '5', factor_type: 'WEATHER', factor_key: 'precipitation',
      factor_value: null, weather_factor: 'precipitation', sources: [],
    }).mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào kho' }));
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 nguồn được lưu để tham khảo/)).toBeInTheDocument();
  });

  it('shows the refreshed WHO source in the library', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('tab', { name: 'Kho nguồn' }));
    expect(await screen.findByText('WHO influenza metadata record')).toBeInTheDocument();
    expect(screen.getByText('WHO')).toBeInTheDocument();
  });

  it('labels WHO metadata-only library content as reference-only', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('tab', { name: 'Kho nguồn' }));
    expect(await screen.findByText('Đã lưu để tham khảo · không thể chọn cho AI Draft.')).toBeInTheDocument();
  });

  it('does not allow WHO metadata-only content to be selected for Draft', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('tab', { name: 'Kho nguồn' }));
    expect(await screen.findByRole('checkbox', { name: /WHO influenza metadata record.*cho bản nháp/ })).toBeDisabled();
  });

  it('adds a mixed PubMed and WHO selection in one strict request', async () => {
    mocks.importProviderSources.mockResolvedValue(importResponse([pubmedAddedOutcome, whoReferenceOutcome]));
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('PubMed mixed evidence'));
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 2 nguồn vào kho' }));
    await waitFor(() => expect(mocks.importProviderSources).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Đã thêm 2 tài liệu/)).toBeInTheDocument();
  });

  it('shows partial batch feedback and retains only the failed selection', async () => {
    const failedWho = { ...whoReferenceOutcome, outcome: 'PROVIDER_ERROR', source_id: null, created: false, topic_link_created: false, message: 'WHO tạm thời không khả dụng.' };
    mocks.importProviderSources.mockResolvedValue(importResponse([pubmedAddedOutcome, failedWho]));
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('PubMed mixed evidence'));
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 2 nguồn vào kho' }));
    expect(await screen.findByText('Đã thêm 1/2 tài liệu. 1 tài liệu không thể thêm.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm 1 nguồn vào kho' })).toBeEnabled();
  });

  it('renders an already-added provider result clearly', async () => {
    const existing = { ...whoReferenceOutcome, outcome: 'ALREADY_EXISTS', created: false, topic_link_created: false };
    mocks.importProviderSources.mockResolvedValue(importResponse([existing]));
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 1 nguồn vào kho' }));
    expect(await screen.findByText('Đã lưu để tham khảo')).toBeInTheDocument();
    expect(await providerResultCheckbox('WHO influenza metadata record')).toBeDisabled();
  });

  it('sends only the explicit provider-neutral import DTO fields', async () => {
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 1 nguồn vào kho' }));
    await waitFor(() => expect(mocks.importProviderSources).toHaveBeenCalledTimes(1));
    const sent = mocks.importProviderSources.mock.calls[0][2][0];
    expect(Object.keys(sent).sort()).toEqual([
      'authors', 'canonical_url', 'doi', 'external_id', 'provider_id', 'publication_date',
      'publication_year', 'publisher_or_journal', 'source_kind', 'title',
    ]);
    expect(sent).not.toHaveProperty('abstract_text');
    expect(sent).not.toHaveProperty('license_name');
    expect(sent).not.toHaveProperty('usable_for_draft');
  });

  it('shows a safe visible error when provider import request fails', async () => {
    mocks.importProviderSources.mockRejectedValue(new ApiError(502, 'private provider stack'));
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào kho' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Không thể xác minh nguồn với nhà cung cấp');
    expect(screen.queryByText('private provider stack')).not.toBeInTheDocument();
  });

  it('clears successful provider selections after import', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào kho' }));
    await waitFor(async () => expect(await providerResultCheckbox('WHO influenza metadata record')).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Thêm 0 nguồn vào kho' })).toBeDisabled();
  });

  it('keeps Draft selection count limited to actually usable library sources', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    fireEvent.click(screen.getByRole('tab', { name: 'Kho nguồn' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Chọn tất cả nguồn AI đọc được' }));
    expect(screen.getByText('1 / 10 nguồn đã chọn')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /WHO influenza metadata record.*cho bản nháp/ })).not.toBeChecked();
  });
});
