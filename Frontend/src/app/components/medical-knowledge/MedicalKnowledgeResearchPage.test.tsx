import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  curationList: vi.fn(), curationCreate: vi.fn(), curationCurrent: vi.fn(), curationProofs: vi.fn(),
}));

vi.mock('@/app/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, username: 'tester', role: mocks.role, permissions: [] } }),
}));

vi.mock('@/lib/parentTrustedReferencesApi', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/parentTrustedReferencesApi')>(),
  listParentReferenceCurations: mocks.curationList, createParentReferenceDraft: mocks.curationCreate,
  getParentReferenceCuration: mocks.curationCurrent, getParentReferenceProofCandidates: mocks.curationProofs,
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
  factor_type: 'WEATHER' as const,
  factor_key: 'precipitation',
  factor_value: null,
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
  fireEvent.change(screen.getByLabelText('2. Yếu tố'), { target: { value: 'WEATHER:precipitation' } });
  await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('5', {
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
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Unexpected network'); }));
    window.history.replaceState({}, '', '/?section=medical-knowledge');
    mocks.role = 'admin';
    mocks.curationList.mockReset().mockImplementation(async (selector) => ({ selector,
      topic_id: (await mocks.getTopicSources.mock.results.at(-1)?.value)?.topic_id ?? 7, items: [],
    }));
    mocks.curationCreate.mockReset(); mocks.curationCurrent.mockReset(); mocks.curationProofs.mockReset();
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
      factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null, weather_factor: 'precipitation',
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
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('170', weatherSelector('precipitation')));
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
    await screen.findByRole('article', { name: 'Duyệt nguồn 10' });
    fireEvent.click(screen.getByRole('button', { name: 'Tìm có hướng dẫn' }));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
    expect(screen.getByText('infectious diarrhea')).toBeInTheDocument();
  });

  it('preserves custom disease keywords when only weather factor changes', async () => {
    await renderReadyPage();
    await chooseContext();
    addTerm('infectious diarrhea');
    fireEvent.change(screen.getByLabelText('2. Yếu tố'), { target: { value: 'WEATHER:humidity' } });
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('5', weatherSelector('humidity')));
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
    expect(screen.getByText('Toàn văn PMC')).toBeInTheDocument();
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
    expect(mocks.importSources).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Tạo bản nháp bằng AI' })).not.toBeInTheDocument();
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
    expect(screen.getAllByText('Trích đoạn toàn văn PMC').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Tóm tắt PubMed').length).toBeGreaterThan(0);
    expect(screen.getByText('PMC123456')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm 0 tài liệu vào kho chủ đề' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Tạo bản nháp bằng AI' })).not.toBeInTheDocument();
  });

  it('loads the persistent topic library without requiring a new PubMed search', async () => {
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByRole('article', { name: 'Duyệt nguồn 10' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /cho bản nháp/ })).not.toBeInTheDocument();
    expect(mocks.search).not.toHaveBeenCalled();
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
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('168', weatherSelector('precipitation')));
    expect(screen.queryByText('Rainfall and pediatric gastroenteritis')).not.toBeInTheDocument();
  });

  it('clears stale results and disease terms when disease group changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('1. Nhóm bệnh'), { target: { value: '1' } });
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('1', weatherSelector('precipitation')));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    expect(screen.queryByText('gastroenteritis')).not.toBeInTheDocument();
  });

  it('clears stale results but keeps disease terms when weather factor changes', async () => {
    await runSuccessfulSearch();
    fireEvent.change(screen.getByLabelText('2. Yếu tố'), { target: { value: 'WEATHER:humidity' } });
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledWith('5', weatherSelector('humidity')));
    expect(screen.queryByText('Tìm thấy 2 tài liệu')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Tìm có hướng dẫn' }));
    expect(screen.getByText('gastroenteritis')).toBeInTheDocument();
  });

  it('keeps generated query collapsed before sources are imported', async () => {
    await runSuccessfulSearch();
    const details = screen.getByText('Chi tiết tìm kiếm').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(screen.queryByRole('button', { name: 'Tạo bản nháp bằng AI' })).not.toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' })).toBeEnabled();
  });

  it('adds one WHO metadata result and refreshes the topic library', async () => {
    mocks.getTopicSources.mockResolvedValueOnce({
      topic_id: null, disease_group_id: '5', factor_type: 'WEATHER', factor_key: 'precipitation',
      factor_value: null, weather_factor: 'precipitation', sources: [],
    }).mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' }));
    await waitFor(() => expect(mocks.getTopicSources).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 nguồn được lưu để tham khảo/)).toBeInTheDocument();
  });

  it('shows the refreshed WHO source in the library', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await renderReadyPage();
    await chooseContext();
    expect(await screen.findByRole('article', { name: 'Duyệt nguồn 30' })).toHaveTextContent('WHO influenza metadata record');
    expect(screen.getByRole('article', { name: 'Duyệt nguồn 30' })).toHaveTextContent('WHO');
  });

  it('adds a mixed PubMed and WHO selection in one strict request', async () => {
    mocks.importProviderSources.mockResolvedValue(importResponse([pubmedAddedOutcome, whoReferenceOutcome]));
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('PubMed mixed evidence'));
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 2 nguồn vào danh sách xem xét' }));
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
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 2 nguồn vào danh sách xem xét' }));
    expect(await screen.findByText('Đã thêm 1/2 tài liệu. 1 tài liệu không thể thêm.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' })).toBeEnabled();
  });

  it('renders an already-added provider result clearly', async () => {
    const existing = { ...whoReferenceOutcome, outcome: 'ALREADY_EXISTS', created: false, topic_link_created: false };
    mocks.importProviderSources.mockResolvedValue(importResponse([existing]));
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' }));
    expect(await screen.findByText('Đã lưu để tham khảo')).toBeInTheDocument();
    expect(await providerResultCheckbox('WHO influenza metadata record')).toBeDisabled();
  });

  it('sends only the explicit provider-neutral import DTO fields', async () => {
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(await screen.findByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' }));
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
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Không thể xác minh nguồn với nhà cung cấp');
    expect(screen.queryByText('private provider stack')).not.toBeInTheDocument();
  });

  it('clears successful provider selections after import', async () => {
    mocks.getTopicSources.mockResolvedValue(mixedTopicLibrary);
    await runMultiProviderSearch();
    fireEvent.click(await providerResultCheckbox('WHO influenza metadata record'));
    fireEvent.click(screen.getByRole('button', { name: 'Thêm 1 nguồn vào danh sách xem xét' }));
    await waitFor(async () => expect(await providerResultCheckbox('WHO influenza metadata record')).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Thêm 0 nguồn vào danh sách xem xét' })).toBeDisabled();
  });

  it('staff curation works with LLM unavailable and no Draft selection UI', async () => {
    mocks.getOptions.mockResolvedValue({ ...options, llm_draft_generation_available: false });
    mocks.getTopicSources.mockResolvedValue({ ...populatedTopicLibrary, sources: [populatedTopicLibrary.sources[0], {
      ...populatedTopicLibrary.sources[1], source_id: 12, provider_id: 'WHO', title: 'WHO reference-only guidance',
      content_kind: null, usable_for_draft: false,
    }] });
    const selector = { disease_group_id: '5', factor_type: 'WEATHER' as const, factor_key: 'precipitation', factor_value: null };
    const current = { approval_id: 80, topic_id: 7, source_id: 12, selector, status: 'DRAFT', version: 1,
      source_in_library: true, policy_decision: 'UNCERTAIN', policy_reason_code: 'MISSING_TRUST_METADATA',
      approved_at: null, source: { original_url: null } };
    mocks.curationCurrent.mockResolvedValue(current);
    mocks.curationCreate.mockImplementation(async () => {
      mocks.curationList.mockResolvedValue({ selector, topic_id: 7, items: [current] });
      return { approval_id: 80, status: 'DRAFT', version: 1, evidence_content_id: null, changed: true };
    });
    mocks.curationProofs.mockResolvedValue({ selector, topic_id: 7, source_id: 12, next_offset: null, candidates: [{
      evidence_content_id: 500, source_id: 12, content_kind: 'OFFICIAL_SUMMARY_EXCERPT', content_origin: 'WHO_PUBLICATIONS_API',
      external_identifier: '1', retrieved_at: '2026-01-01T00:00:00', content_sha256: 'a'.repeat(64),
      policy_decision: 'ALLOW_PARENT_REFERENCE', policy_reason_code: 'WHO_OFFICIAL_GUIDANCE',
    }] });
    await renderReadyPage('staff'); await chooseContext();
    const panel = screen.getByRole('region', { name: 'Duyệt nguồn tham khảo cho phụ huynh' });
    const card = await within(panel).findByRole('article', { name: 'Duyệt nguồn 12' });
    fireEvent.click(within(card).getByRole('button', { name: 'Bắt đầu duyệt cho phụ huynh' }));
    await within(panel).findByText('Phụ huynh: Đang xem xét');
    expect(mocks.curationCreate).toHaveBeenCalledWith(selector, 12, '', expect.any(AbortSignal));
    fireEvent.click(within(panel).getByRole('button', { name: 'Chọn bằng chứng xác minh' }));
    fireEvent.click(await within(panel).findByRole('radio', { name: 'Chọn bằng chứng #500' }));
    expect(within(panel).getByRole('button', { name: 'Duyệt và hiển thị cho phụ huynh' })).toBeEnabled();
    expect(mocks.generateDraft).not.toHaveBeenCalled();
    expect(screen.queryByRole('checkbox', { name: /cho bản nháp/ })).not.toBeInTheDocument();
  });

  it('curation mutation errors retain source management without legacy generation', async () => {
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    mocks.curationCreate.mockRejectedValue(new ApiError(422, 'private curation error'));
    await renderReadyPage('staff'); await chooseContext();
    const panel = screen.getByRole('region', { name: 'Duyệt nguồn tham khảo cho phụ huynh' });
    fireEvent.click((await within(panel).findAllByRole('button', { name: 'Bắt đầu duyệt cho phụ huynh' }))[0]);
    await within(panel).findByRole('alert');
    expect(mocks.generateDraft).not.toHaveBeenCalled(); expect(screen.queryByText('private curation error')).not.toBeInTheDocument();
  });

  it('unauthorized roles never mount Staff Curation', async () => {
    mocks.role = 'parent'; render(<MedicalKnowledgeResearchPage />);
    expect(screen.queryByRole('region', { name: 'Duyệt nguồn tham khảo cho phụ huynh' })).not.toBeInTheDocument();
    expect(mocks.curationList).not.toHaveBeenCalled();
  });
  it.each(['auto', 'reviewed', 'invalid'])('disconnects generated workflows even for old knowledgeView=%s URLs', async view => {
    window.history.replaceState({}, '', '/?section=medical-knowledge&knowledgeView=' + view);
    await renderReadyPage(); await chooseContext();
    for (const label of ['Kiến thức tự động', 'Kiến thức đã kiểm duyệt', 'Nguồn AI sẽ đọc', 'AI draft provider', 'Revision & kiểm duyệt']) {
      expect(screen.queryByText(label, { exact: false })).not.toBeInTheDocument();
    }
    expect(mocks.getAutoOverview).not.toHaveBeenCalled(); expect(mocks.generateDraft).not.toHaveBeenCalled();
    expect(mocks.getHistory).not.toHaveBeenCalled(); expect(mocks.getServiceStatus).not.toHaveBeenCalled();
  });
  it('orders context, approved sources, search and curation without a dashboard hero', async () => {
    mocks.getTopicSources.mockResolvedValue(populatedTopicLibrary);
    await renderReadyPage(); await chooseContext();
    await screen.findByRole('article', { name: 'Duyệt nguồn 10' });
    const headings = screen.getAllByRole('heading').map(item => item.textContent);
    expect(headings.slice(0, 5)).toEqual(['Nguồn tham khảo tin cậy', 'Ngữ cảnh tham khảo', 'Nguồn đang hiển thị cho phụ huynh', 'Tìm và thêm nguồn', 'Nguồn tìm kiếm']);
    expect(headings.indexOf('Nguồn chờ duyệt / quản lý curation')).toBeGreaterThan(headings.indexOf('Tìm và thêm nguồn'));
    expect(document.querySelector('[class*="gradient"]')).toBeNull();
  });

});
