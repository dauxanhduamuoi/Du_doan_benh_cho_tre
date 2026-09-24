import { ApiError, request } from './api';
import type {
  ExplanationFactorOption,
  MedicalFactorSelector,
  MedicalFactorType,
} from './medicalKnowledgeFactors';

export type { ExplanationFactorOption, MedicalFactorSelector, MedicalFactorType } from './medicalKnowledgeFactors';

export interface DiseaseGroupOption {
  id: string;
  name: string;
  english_name?: string | null;
}

export interface WeatherFactorOption {
  value: string;
  label_vi: string;
}

export interface MedicalKnowledgeOptions {
  disease_groups: DiseaseGroupOption[];
  weather_factors: WeatherFactorOption[];
  explanation_factors: ExplanationFactorOption[];
  llm_draft_generation_available: boolean;
}

export interface MedicalKnowledgeServiceStatus {
  pubmed: {
    configured: boolean;
    email_configured: boolean;
    api_key_configured: boolean;
  };
  llm: {
    configured: boolean;
    provider: string;
    model: string | null;
    api_key_configured: boolean;
    mode: 'local' | 'remote' | 'cloud_api' | 'unknown';
    local: boolean;
  };
}

export type MedicalEvidenceWorkflow = 'AUTO' | 'REVIEWED';

export interface MedicalEvidenceProviderSetting {
  provider_id: string;
  display_name: string;
  description: string;
  workflow: MedicalEvidenceWorkflow;
  enabled: boolean;
  capabilities: string[];
  operational_status: 'REGISTERED';
  updated_at: string;
  updated_by: number | null;
}

export interface MedicalEvidenceProviderSettingsResponse {
  providers: MedicalEvidenceProviderSetting[];
}

export interface ReviewedProviderSource {
  provider_id: string;
  external_id: string;
  source_kind: string;
  title: string;
  authors: string | null;
  publisher_or_journal: string | null;
  publication_date: string | null;
  publication_year: number | null;
  doi: string | null;
  url: string | null;
  abstract_text: string | null;
  license_name: string | null;
  license_url: string | null;
  usability: 'USABLE_FOR_DRAFT' | 'METADATA_ONLY';
  usable_for_draft: boolean;
  source_id: number | null;
  in_topic_library: boolean;
  relevance: 'DIRECT_TOPIC' | 'RELATED_CONTEXT' | 'BROAD_CONTEXT' | 'REJECT' | 'EXACT_LOOKUP';
  query_level: string;
}

export interface ReviewedProviderQueryAttempt {
  level: string;
  relevance: 'DIRECT_TOPIC' | 'RELATED_CONTEXT' | 'BROAD_CONTEXT';
  query: string;
  provider_match_count: number;
  fetched_count: number;
  normalized_count: number;
  disease_match_count: number;
  factor_match_count: number;
  relevant_count: number;
  direct_count: number;
  related_count: number;
  rejected_count: number;
  pages_fetched: number;
  budget_exhausted: boolean;
  provider_exhausted: boolean;
  stop_reason: 'TARGET_REACHED' | 'PROVIDER_EXHAUSTED' | 'CANDIDATE_BUDGET_REACHED' | 'QUERY_ATTEMPT_COMPLETE' | 'PROVIDER_ERROR';
  status: 'SUCCESS' | 'PROVIDER_ERROR';
  warning: { provider_id: string; code: string; message: string } | null;
}

export interface ReviewedProviderSearchResponse {
  requested_count: number;
  provider_count: number;
  max_candidates: number;
  count: number;
  unique_count: number;
  providers: ReviewedProviderSearchGroup[];
  results: ReviewedProviderSource[];
  queries: Record<string, string>;
  warnings: Array<{ provider_id: string; code: string; message: string }>;
}

export interface ReviewedProviderSearchGroup {
  provider_id: string;
  display_name: string;
  requested_count: number;
  requested_relevant_count: number;
  effective_limit: number;
  returned_count: number;
  total_available: number | null;
  provider_total_available: number | null;
  provider_invoked: boolean;
  provider_status: 'SUCCESS' | 'PROVIDER_ERROR';
  raw_result_count: number;
  raw_candidates_examined: number;
  normalized_count: number;
  normalized_candidates: number;
  disease_match_count: number;
  factor_match_count: number;
  relevant_count: number;
  rejected_count: number;
  pages_fetched: number;
  budget_exhausted: boolean;
  provider_exhausted: boolean;
  stop_reason: 'TARGET_REACHED' | 'PROVIDER_EXHAUSTED' | 'CANDIDATE_BUDGET_REACHED' | 'QUERY_PLAN_EXHAUSTED' | 'PROVIDER_ERROR';
  direct_count: number;
  related_count: number;
  contextual_count: number;
  status: 'SUCCESS' | 'NO_RESULTS' | 'PROVIDER_ERROR';
  query: string;
  warning: { provider_id: string; code: string; message: string } | null;
  query_attempts: ReviewedProviderQueryAttempt[];
  results: ReviewedProviderSource[];
}

export type ReviewedProviderImportOutcome =
  | 'ADDED'
  | 'ADDED_REFERENCE_ONLY'
  | 'ALREADY_EXISTS'
  | 'REJECTED_INVALID'
  | 'PROVIDER_ERROR';

export interface ReviewedProviderImportSource {
  outcome: ReviewedProviderImportOutcome;
  source_id: number | null;
  provider_id: string;
  external_id: string;
  title: string | null;
  created: boolean;
  topic_link_created: boolean;
  content_kind: EvidenceContentKind | null;
  license_name: string | null;
  license_url: string | null;
  usable_for_draft: boolean;
  imported_at: string | null;
  message: string | null;
}

export interface ReviewedProviderImportResponse {
  topic_id: number | null;
  count: number;
  requested_count: number;
  added_count: number;
  reference_only_count: number;
  already_exists_count: number;
  failed_count: number;
  sources: ReviewedProviderImportSource[];
}

export interface ReviewedProviderImportReference {
  provider_id: string;
  external_id: string;
  canonical_url: string | null;
  source_kind: string;
  title: string;
  authors: string | null;
  publisher_or_journal: string | null;
  publication_date: string | null;
  publication_year: number | null;
  doi: string | null;
}

export type AutoMedicalKnowledgeDisplayMode = 'REVIEWED_ONLY' | 'REVIEWED_WITH_AUTO_FALLBACK';
export type AutoMedicalKnowledgeJobStatus =
  | 'QUEUED' | 'SEARCHING' | 'GENERATING' | 'READY' | 'INSUFFICIENT' | 'FAILED' | 'CANCELLED';

export interface AutoMedicalKnowledgeSettings {
  enabled: boolean;
  display_mode: AutoMedicalKnowledgeDisplayMode;
  auto_visible_default: boolean;
  basic_fallback_enabled: boolean;
}

export interface AutoDiscoveryDiagnostics {
  attempt: number;
  queries_run: number;
  raw_results: number;
  deduplicated: number;
  disease_relevant: number;
  factor_relevant: number;
  pediatric_relevant: number;
  usable_evidence: number;
  selected_for_generation: number;
  insufficient_reason: string | null;
  queries: string[];
  sources: Array<{
    pmid: string;
    title: string;
    decision: 'SELECTED' | 'SKIPPED';
    reason_code: string;
    stage: string | null;
  }>;
  pipeline_version: string | null;
  failure: {
    code: string;
    field: string | null;
    source_id: number | null;
    numeric_value: string | null;
    safe_detail: string;
    provider_error_class: string | null;
    provider?: string | null;
    http_status?: number | null;
    provider_stage?: string | null;
    finish_reason?: string | null;
    choices_count?: number | null;
    message_present?: boolean | null;
    content_present?: boolean | null;
    content_length?: number | null;
    refusal_present?: boolean | null;
    incomplete?: boolean | null;
    structured_field_detected?: string | null;
    call_purpose?: 'INITIAL' | 'STRUCTURAL_RETRY' | 'CONTRACT_REPAIR' | 'BASIC' | null;
    generation_call_number?: number | null;
    response_format_type?: string | null;
    provider_validation_stage?: string | null;
    provider_error_category?: string | null;
    provider_error_type?: string | null;
    request_body_bytes?: number | null;
    user_content_chars?: number | null;
    message_count?: number | null;
    generation_calls?: number | null;
    max_generation_calls?: number | null;
    contract_repair_attempted?: boolean | null;
    contract_repair_reason?: string | null;
    contract_repair_calls?: number | null;
    contract_repair_result?: string | null;
    basic_attempted?: boolean | null;
    basic_calls?: number | null;
    basic_result?: string | null;
    strict_failure_code?: string | null;
    strict_failure_stage?: string | null;
  } | null;
}

export interface AutoMedicalKnowledgeJob {
  id: number;
  topic_id: number;
  disease_group_id: string;
  disease_group_name: string;
  factor_type: MedicalFactorType;
  factor_key: string;
  factor_value: string | null;
  status: AutoMedicalKnowledgeJobStatus;
  attempt_count: number;
  trigger_type: 'PARENT' | 'ADMIN';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  next_retry_at: string | null;
  last_error_code: string | null;
  is_current_attempt: boolean;
  legacy: boolean;
  pipeline_version: string | null;
  history: Array<{
    attempt: number;
    status: 'FAILED' | 'UNKNOWN';
    failure_code: string | null;
    legacy: boolean;
    pipeline_version: string | null;
    created_at: string;
  }>;
  diagnostics: AutoDiscoveryDiagnostics | null;
}

export interface AutoMedicalKnowledgeSource {
  source_id: number;
  provider_id?: string;
  source_kind?: string;
  title: string;
  journal: string | null;
  publication_year: number | null;
  pmid: string | null;
  doi: string | null;
  url: string | null;
  trust_class: string;
  content_kind: string;
  source_role: string;
  relevance_note: string;
  population_relevance: PopulationRelevance;
  population_note: string;
}

export interface AutoMedicalKnowledgeRevision extends MedicalFactorSelector {
  id: number;
  topic_id: number;
  disease_group_id: string;
  disease_group_name: string;
  revision_number: number;
  generation_status: 'READY' | 'INSUFFICIENT';
  generation_mode?: 'AI_FULL' | 'SAFE_FALLBACK' | null;
  auto_tier?: 'STRICT' | 'BASIC' | null;
  generation_method?: 'AI' | 'SAFE_TEMPLATE' | null;
  strict_failure_code?: string | null;
  strict_failure_stage?: string | null;
  fallback_reason_code?: 'CONTRACT_REPAIR_EXHAUSTED' | 'REPAIR_PROVIDER_FAILURE' | 'REPAIR_STRUCTURAL_FAILURE' | null;
  evidence_level: EvidenceLevel;
  evidence_scope: EvidenceScope | null;
  short_explanation_vi: string | null;
  detailed_explanation_vi: string | null;
  limitations_vi: string | null;
  is_visible: boolean;
  auto_display_eligible: boolean;
  topic_hidden_by_staff: boolean;
  topic_hidden_at: string | null;
  llm_model: string | null;
  prompt_version: string;
  generated_at: string;
  source_retrieved_at: string | null;
  sources: AutoMedicalKnowledgeSource[];
  diagnostics: AutoDiscoveryDiagnostics | null;
}

export interface AutoMedicalKnowledgeOverview {
  settings: AutoMedicalKnowledgeSettings;
  provider_cooldown: {
    provider: string;
    active: boolean;
    cooldown_until: string;
    reason: string;
    updated_at: string;
  } | null;
  jobs: AutoMedicalKnowledgeJob[];
  revisions: AutoMedicalKnowledgeRevision[];
}

export interface ServiceConnectionTestResult {
  ok: boolean;
  message: string;
}

export type EvidenceLevel = 'SUPPORTED' | 'LIMITED_OR_INDIRECT' | 'CONFLICTING' | 'INSUFFICIENT';
export type EvidenceScope = 'WHOLE_GROUP' | 'PARTIAL_GROUP';
export type RevisionStatus = 'DRAFT' | 'APPROVED' | 'REJECTED';
export type EvidenceContentKind = 'ABSTRACT' | 'PMC_FULL_TEXT' | 'PMC_FULL_TEXT_EXCERPT' | 'OFFICIAL_SUMMARY_EXCERPT';
export type PopulationRelevance =
  | 'PEDIATRIC_DIRECT'
  | 'MIXED_AGE'
  | 'ADULT_ONLY'
  | 'ELDERLY_ONLY'
  | 'UNKNOWN';

export interface DraftSource {
  id: number;
  source_type: string;
  pmid: string | null;
  doi: string | null;
  title: string;
  authors: string | null;
  journal: string | null;
  publication_year: number | null;
  abstract_text: string | null;
  url: string | null;
  content_kind: EvidenceContentKind | null;
  pmcid: string | null;
  content_origin: string;
  source_role: string;
  sort_order: number;
  relevance_note: string | null;
  population_relevance?: PopulationRelevance | null;
  population_note?: string | null;
}

export interface DraftRevisionSummary {
  id: number;
  revision_number: number;
  status: RevisionStatus;
  evidence_level: EvidenceLevel;
  evidence_scope: EvidenceScope;
  generated_by_llm: boolean;
  created_at: string;
  updated_at: string;
  is_published?: boolean;
}

export interface DraftRevision extends DraftRevisionSummary {
  topic_id: number;
  disease_group_id: string;
  disease_group_name: string;
  factor_type: MedicalFactorType;
  factor_key: string;
  factor_value: string | null;
  weather_factor: string | null;
  short_explanation_vi: string;
  detailed_explanation_vi: string;
  limitations_vi: string;
  parent_display_allowed: boolean;
  llm_model: string | null;
  prompt_version: string | null;
  created_by: number | null;
  reviewed_by: number | null;
  reviewed_by_name?: string | null;
  reviewed_at: string | null;
  published_by?: number | null;
  published_by_name?: string | null;
  published_at?: string | null;
  sources: DraftSource[];
  parent_tier2_eligible?: boolean;
  parent_tier2_ineligibility_reasons?: string[];
}

export interface DraftTopicHistory {
  topic: {
    id: number;
    disease_group_id: string;
    disease_group_name: string;
    factor_type: MedicalFactorType;
    factor_key: string;
    factor_value: string | null;
    weather_factor: string | null;
    published_revision_id: number | null;
  } | null;
  revisions: DraftRevisionSummary[];
}

export interface DraftRevisionPatch {
  evidence_level: EvidenceLevel;
  evidence_scope: EvidenceScope;
  short_explanation_vi: string;
  detailed_explanation_vi: string;
  limitations_vi: string;
}

export interface RevisionApproval {
  revision_id: number;
  status: 'APPROVED';
  approved_by: number;
  approved_by_name: string;
  approved_at: string;
  parent_display_allowed: false;
  published_revision_id: number | null;
}

export interface RevisionPublication {
  revision_id: number;
  topic_id: number;
  status: 'APPROVED';
  is_published: true;
  parent_display_allowed: true;
  published_by: number;
  published_by_name: string;
  published_at: string;
  previous_published_revision_id: number | null;
}

export interface RevisionUnpublication {
  revision_id: number;
  topic_id: number;
  status: 'APPROVED';
  is_published: false;
  parent_display_allowed: false;
  unpublished_by: number;
  unpublished_by_name: string;
  unpublished_at: string;
}

export interface PubMedSearchPayload extends MedicalFactorSelector {
  disease_group_id: string;
  search_mode?: 'GUIDED' | 'FREE';
  disease_terms?: string[];
  free_query?: string | null;
  max_results: 10 | 15 | 20 | 25;
  year_from?: number | null;
  year_to?: number | null;
}

export interface PubMedPaper {
  pmid: string;
  title: string;
  authors: string | null;
  journal: string | null;
  publication_year: number | null;
  doi: string | null;
  abstract_text: string | null;
  pubmed_url: string;
  pmcid?: string | null;
  source_id?: number | null;
  stored_globally?: boolean;
  in_topic_library?: boolean;
  content_kind?: EvidenceContentKind | null;
}

export interface PubMedSearchResponse extends MedicalFactorSelector {
  disease_group_id: string;
  search_mode: 'GUIDED' | 'FREE';
  query: string;
  count: number;
  results: PubMedPaper[];
}

export interface PubMedLookupResponse {
  pmid: string;
  result: PubMedPaper;
  existing_source: PubMedImportedSource | null;
}

export interface PubMedImportedSource {
  id: number;
  pmid: string;
  created: boolean;
  title: string;
  retrieved_at: string | null;
  content_kind: EvidenceContentKind | null;
  pmcid: string | null;
  source_reused: boolean;
  topic_link_created: boolean;
  already_in_topic_library: boolean;
}

export interface TopicSourceLibraryItem {
  source_id: number;
  provider_id?: string;
  external_id?: string | null;
  source_kind?: string;
  pmid: string | null;
  title: string;
  journal: string | null;
  publication_year: number | null;
  doi: string | null;
  pmcid: string | null;
  content_kind: EvidenceContentKind | null;
  url?: string | null;
  license_name?: string | null;
  license_url?: string | null;
  usable_for_draft?: boolean;
  added_at: string;
}

export interface TopicSourceLibrary extends MedicalFactorSelector {
  topic_id: number | null;
  disease_group_id: string;
  sources: TopicSourceLibraryItem[];
}

export const MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES = 10;

export function isTopicSourceAiReadable(source: TopicSourceLibraryItem): boolean {
  return source.usable_for_draft ?? source.content_kind !== null;
}

export function evidenceContentLabel(kind: EvidenceContentKind | null): string {
  if (kind === 'PMC_FULL_TEXT') return 'AI sử dụng: Toàn văn PMC';
  if (kind === 'PMC_FULL_TEXT_EXCERPT') return 'AI sử dụng: Trích đoạn toàn văn PMC';
  if (kind === 'ABSTRACT') return 'AI sử dụng: Tóm tắt PubMed';
  if (kind === 'OFFICIAL_SUMMARY_EXCERPT') return 'AI sử dụng: Trích đoạn chính thức WHO';
  return 'AI chưa có nội dung để đọc';
}

export interface PubMedImportResponse {
  topic_id: number;
  count: number;
  created_count: number;
  reused_count: number;
  sources: PubMedImportedSource[];
}

export function getMedicalKnowledgeOptions(): Promise<MedicalKnowledgeOptions> {
  return request<MedicalKnowledgeOptions>('/api/medical-knowledge/options');
}

export function getMedicalKnowledgeServiceStatus(): Promise<MedicalKnowledgeServiceStatus> {
  return request<MedicalKnowledgeServiceStatus>('/api/medical-knowledge/service-status');
}

export function getMedicalEvidenceProviderSettings(): Promise<MedicalEvidenceProviderSettingsResponse> {
  return request<MedicalEvidenceProviderSettingsResponse>('/api/medical-knowledge/providers/settings');
}

export function updateMedicalEvidenceProviderSetting(payload: {
  provider_id: string;
  workflow: MedicalEvidenceWorkflow;
  enabled: boolean;
}): Promise<MedicalEvidenceProviderSettingsResponse> {
  return request<MedicalEvidenceProviderSettingsResponse>('/api/medical-knowledge/providers/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function searchMedicalEvidenceProviders(payload: {
  disease_group_id: string;
  factor_type: MedicalFactorType;
  factor_key: string;
  factor_value: string | null;
  weather_factor?: string | null;
  disease_terms: string[];
  provider_ids: string[];
  max_results: number;
  year_from: number | null;
  year_to: number | null;
}): Promise<ReviewedProviderSearchResponse> {
  return request<ReviewedProviderSearchResponse>('/api/medical-knowledge/providers/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
}

export function importMedicalEvidenceProviderSources(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
  sources: ReviewedProviderImportReference[],
): Promise<ReviewedProviderImportResponse> {
  return request<ReviewedProviderImportResponse>('/api/medical-knowledge/providers/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disease_group_id: diseaseGroupId, ...factor, sources }),
  });
}

export function lookupMedicalEvidenceExact(
  providerId: string, identifier: string, diseaseGroupId: string, factor: MedicalFactorSelector,
): Promise<{ lookup_mode: 'EXACT'; requested_identifier: string; result: ReviewedProviderSource }> {
  return request('/api/medical-knowledge/providers/lookup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_id: providerId, identifier, disease_group_id: diseaseGroupId, ...factor }),
  });
}

export function getAutoMedicalKnowledgeOverview(): Promise<AutoMedicalKnowledgeOverview> {
  return request<AutoMedicalKnowledgeOverview>('/api/medical-knowledge/auto');
}

export function updateAutoMedicalKnowledgeSettings(payload: {
  enabled?: boolean;
  display_mode?: AutoMedicalKnowledgeDisplayMode;
  auto_visible_default?: boolean;
  basic_fallback_enabled?: boolean;
}): Promise<AutoMedicalKnowledgeSettings> {
  return request<AutoMedicalKnowledgeSettings>('/api/medical-knowledge/auto/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function setAutoMedicalKnowledgeTopicVisibility(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
  hidden: boolean,
): Promise<{ ok: boolean; topic_id: number; message: string }> {
  return request('/api/medical-knowledge/auto/topics/visibility', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      disease_group_id: diseaseGroupId,
      factor_type: factor.factor_type,
      factor_key: factor.factor_key,
      factor_value: factor.factor_value,
      weather_factor: factor.weather_factor,
      hidden,
    }),
  });
}

export function retryAutoMedicalKnowledgeJob(
  jobId: number,
): Promise<{ ok: boolean; job_id: number; message: string }> {
  return request(`/api/medical-knowledge/auto/jobs/${jobId}/retry`, { method: 'POST' });
}

export function regenerateAutoMedicalKnowledge(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
): Promise<{
  ok: boolean;
  job_id: number | null;
  created: boolean;
  outcome: 'CREATED' | 'ALREADY_ACTIVE' | 'WAITING_RETRY' | 'PROVIDER_COOLDOWN';
  job_status: AutoMedicalKnowledgeJobStatus | null;
  message: string;
}> {
  return request('/api/medical-knowledge/auto/regenerate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      disease_group_id: diseaseGroupId,
      factor_type: factor.factor_type,
      factor_key: factor.factor_key,
      factor_value: factor.factor_value,
      weather_factor: factor.weather_factor,
    }),
  });
}

export function autoMedicalKnowledgeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return 'Bạn không có quyền thay đổi hiển thị hoặc chạy lại Auto Knowledge.';
    if (error.status === 409) return 'Chủ đề đã có job đang xử lý hoặc trạng thái hiện tại không thể chạy lại.';
    if (error.status === 422) return 'Auto Knowledge này chưa đủ điều kiện an toàn để hiển thị.';
  }
  return 'Không thể cập nhật Auto Medical Knowledge lúc này.';
}

export function testPubMedConnection(): Promise<ServiceConnectionTestResult> {
  return request<ServiceConnectionTestResult>('/api/medical-knowledge/service-status/pubmed/test', {
    method: 'POST',
  });
}

export function testLlmConnection(): Promise<ServiceConnectionTestResult> {
  return request<ServiceConnectionTestResult>('/api/medical-knowledge/service-status/llm/test', {
    method: 'POST',
  });
}

export function searchPubMed(payload: PubMedSearchPayload): Promise<PubMedSearchResponse> {
  return request<PubMedSearchResponse>('/api/medical-knowledge/pubmed/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function lookupPubMedByPmid(
  pmid: string,
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
): Promise<PubMedLookupResponse> {
  return request<PubMedLookupResponse>('/api/medical-knowledge/pubmed/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pmid,
      disease_group_id: diseaseGroupId,
      ...factor,
    }),
  });
}

export function importPubMedSources(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
  pmids: string[],
): Promise<PubMedImportResponse> {
  return request<PubMedImportResponse>('/api/medical-knowledge/pubmed/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      disease_group_id: diseaseGroupId,
      ...factor,
      pmids,
    }),
  });
}

export function getMedicalKnowledgeTopicSources(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
): Promise<TopicSourceLibrary> {
  const query = new URLSearchParams({
    disease_group_id: diseaseGroupId,
    factor_type: factor.factor_type,
    factor_key: factor.factor_key,
  });
  if (factor.factor_value) query.set('factor_value', factor.factor_value);
  return request<TopicSourceLibrary>(`/api/medical-knowledge/topic-sources?${query.toString()}`);
}

export function generateMedicalKnowledgeDraft(payload: {
  disease_group_id: string;
  factor_type: MedicalFactorType;
  factor_key: string;
  factor_value: string | null;
  weather_factor?: string | null;
  source_ids: number[];
}): Promise<DraftRevision> {
  return request<DraftRevision>('/api/medical-knowledge/drafts/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function getMedicalKnowledgeDraftHistory(
  diseaseGroupId: string,
  factor: MedicalFactorSelector,
): Promise<DraftTopicHistory> {
  const query = new URLSearchParams({
    disease_group_id: diseaseGroupId,
    factor_type: factor.factor_type,
    factor_key: factor.factor_key,
  });
  if (factor.factor_value) query.set('factor_value', factor.factor_value);
  return request<DraftTopicHistory>(`/api/medical-knowledge/topics?${query.toString()}`);
}

export function getMedicalKnowledgeRevision(revisionId: number): Promise<DraftRevision> {
  return request<DraftRevision>(`/api/medical-knowledge/revisions/${revisionId}`);
}

export function updateMedicalKnowledgeDraft(
  revisionId: number,
  payload: DraftRevisionPatch,
): Promise<DraftRevision> {
  return request<DraftRevision>(`/api/medical-knowledge/revisions/${revisionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function approveMedicalKnowledgeRevision(revisionId: number): Promise<RevisionApproval> {
  return request<RevisionApproval>(`/api/medical-knowledge/revisions/${revisionId}/approve`, {
    method: 'POST',
  });
}

export function publishMedicalKnowledgeRevision(revisionId: number): Promise<RevisionPublication> {
  return request<RevisionPublication>(`/api/medical-knowledge/revisions/${revisionId}/publish`, {
    method: 'POST',
  });
}

export function unpublishMedicalKnowledgeRevision(revisionId: number): Promise<RevisionUnpublication> {
  return request<RevisionUnpublication>(`/api/medical-knowledge/revisions/${revisionId}/unpublish`, {
    method: 'POST',
  });
}

export function medicalKnowledgeUnpublicationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền ngừng xuất bản phiên bản này.';
    if (error.status === 404) return 'Không tìm thấy phiên bản cần ngừng xuất bản.';
    if (error.status === 409) return 'Chỉ phiên bản đang được xuất bản hiện tại mới có thể ngừng xuất bản.';
    if (error.status === 422) return 'Phiên bản hoặc người thực hiện không hợp lệ.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return 'Không thể ngừng xuất bản phiên bản lúc này. Vui lòng thử lại.';
}

export function medicalKnowledgePublicationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền xuất bản phiên bản này.';
    if (error.status === 404) return 'Không tìm thấy phiên bản cần xuất bản.';
    if (error.status === 409) return 'Chỉ phiên bản APPROVED chưa bị thay đổi đồng thời mới có thể xuất bản.';
    if (error.status === 422) return 'Phiên bản hoặc người xuất bản không hợp lệ.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return 'Không thể xuất bản phiên bản lúc này. Vui lòng thử lại.';
}

export function medicalKnowledgeApprovalErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'APPROVAL_PEDIATRIC_SUPPORT_REQUIRED') {
      return 'Không thể duyệt mức SUPPORTED: cần ít nhất một nguồn vừa hỗ trợ trực tiếp quan hệ bệnh–thời tiết vừa nghiên cứu trực tiếp trên trẻ em.';
    }
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền duyệt phiên bản này.';
    if (error.status === 404) return 'Không tìm thấy phiên bản cần duyệt.';
    if (error.status === 409) return 'Phiên bản này không còn ở trạng thái DRAFT hoặc đã được duyệt.';
    if (error.status === 422) return 'Nội dung hoặc nguồn của phiên bản chưa hợp lệ để duyệt.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return 'Không thể duyệt phiên bản lúc này. Vui lòng thử lại.';
}

export function medicalKnowledgeDraftErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const codedMessages: Record<string, string> = {
      DRAFT_NO_SOURCES_SELECTED: 'Bạn chưa chọn tài liệu nào cho bản nháp.',
      DRAFT_SOURCE_NOT_IN_TOPIC: 'Một hoặc nhiều tài liệu đã chọn không thuộc kho nguồn của chủ đề hiện tại. Danh sách chọn đã được làm mới.',
      DRAFT_SOURCE_NOT_FOUND: 'Một hoặc nhiều tài liệu đã chọn không còn tồn tại trong hệ thống.',
      DRAFT_TOO_MANY_SOURCES: 'Một bản nháp hiện hỗ trợ tối đa 10 nguồn.',
      DRAFT_SOURCE_NO_USABLE_EVIDENCE: 'Một hoặc nhiều tài liệu đã chọn chưa có nội dung mà AI có thể đọc.',
      DRAFT_SOURCE_EVIDENCE_MISMATCH: 'Nội dung bằng chứng của tài liệu đã chọn không còn nhất quán. Vui lòng tải lại kho nguồn.',
      DRAFT_SCOPE_WHOLE_GROUP_REQUIRES_DIRECT: 'AI đề xuất phạm vi áp dụng cho toàn nhóm bệnh, nhưng các nguồn hiện tại chưa có ít nhất một nguồn trực tiếp phù hợp. Bản nháp chưa được lưu.',
      DRAFT_SUPPORTED_REQUIRES_PEDIATRIC_SOURCE: 'AI đề xuất SUPPORTED nhưng chưa có cùng một nguồn vừa hỗ trợ trực tiếp quan hệ bệnh–thời tiết vừa nghiên cứu trực tiếp trên trẻ em. Bản nháp chưa được lưu.',
      DRAFT_PROPOSAL_INVALID: 'AI trả về bản đề xuất chưa đáp ứng quy tắc kiểm tra. Vui lòng xem lại nguồn hoặc thử tạo lại.',
      DRAFT_TOPIC_MISMATCH: 'Chủ đề đã thay đổi hoặc chưa có kho nguồn. Danh sách chọn đã được làm mới.',
    };
    if (error.code && codedMessages[error.code]) return codedMessages[error.code];
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền sử dụng chức năng này.';
    if (error.status === 404) return 'Không tìm thấy nhóm bệnh, nguồn hoặc bản nháp được yêu cầu.';
    if (error.status === 409) return 'Chỉ bản nháp ở trạng thái DRAFT mới có thể chỉnh sửa.';
    if (error.status === 429) return 'Đã đạt giới hạn sử dụng nhà cung cấp AI. Hãy thử lại sau.';
    if (error.status === 503) return 'Chức năng tạo bản nháp bằng AI chưa được cấu hình.';
    if (error.status === 502) return 'AI chưa thể tạo bản nháp hợp lệ. Vui lòng thử lại sau.';
    if (error.status === 422) return 'Yêu cầu tạo bản nháp chưa hợp lệ. Vui lòng tải lại kho nguồn và kiểm tra lựa chọn.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return error instanceof Error ? error.message : 'Đã có lỗi xảy ra. Vui lòng thử lại.';
}

export function medicalKnowledgeErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền sử dụng chức năng này.';
    if (error.status === 404) return 'Nhóm bệnh không thuộc phiên bản Weather AI hiện tại.';
    if (error.status === 503) return 'PubMed chưa được cấu hình đầy đủ trên máy chủ.';
    if (error.status === 502) return 'Hiện không thể kết nối PubMed. Vui lòng thử lại sau.';
    if (error.status === 422) return 'Thông tin tìm kiếm chưa hợp lệ. Vui lòng kiểm tra lại.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return error instanceof Error ? error.message : 'Đã có lỗi xảy ra. Vui lòng thử lại.';
}

export function medicalEvidenceImportErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền thêm nguồn vào kho chủ đề.';
    if (error.status === 422) return 'Thông tin nguồn không hợp lệ hoặc nguồn chưa được bật cho tìm kiếm kiểm duyệt.';
    if (error.status === 502) return 'Không thể xác minh nguồn với nhà cung cấp lúc này. Vui lòng thử lại sau.';
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return 'Không thể thêm nguồn vào kho chủ đề. Vui lòng thử lại.';
}

export function directPmidErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'Không tìm thấy bài PubMed với PMID này.';
    if (error.status === 422) return 'PMID chỉ gồm các chữ số.';
  }
  return medicalKnowledgeErrorMessage(error);
}

const SAFE_LOCAL_AI_DETAILS = new Set([
  'Chưa chọn model AI cục bộ.',
  'Model AI cục bộ chưa được cài đặt trong Ollama.',
  'AI cục bộ phản hồi quá lâu.',
  'AI cục bộ trả dữ liệu không đúng định dạng.',
  'Không kết nối được AI cục bộ Ollama. Hãy mở Ollama trên máy và thử lại.',
  'Cấu hình nhà cung cấp AI không hợp lệ.',
]);

const SAFE_GROQ_DETAILS = new Set([
  'Chưa cấu hình GROQ_API_KEY.',
  'Không thể xác thực với Groq.',
  'Model Groq đã cấu hình không khả dụng.',
  'Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau.',
  'Groq phản hồi quá lâu.',
  'Groq trả dữ liệu không đúng định dạng.',
  'Hiện không thể kết nối Groq.',
  'Cấu hình nhà cung cấp AI không hợp lệ.',
]);

export function serviceConfigurationErrorMessage(
  error: unknown,
  service: 'PubMed' | 'OpenAI' | 'AI cục bộ' | 'Groq',
): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền kiểm tra cấu hình dịch vụ.';
    if (service === 'AI cục bộ' && SAFE_LOCAL_AI_DETAILS.has(error.detail)) return error.detail;
    if (service === 'Groq' && SAFE_GROQ_DETAILS.has(error.detail)) return error.detail;
    if (error.status === 503) return `${service} chưa được cấu hình đầy đủ.`;
    if (error.status >= 500) return `Hiện không thể kết nối ${service}. Vui lòng thử lại sau.`;
  }
  if (error instanceof TypeError) return 'Không thể kết nối máy chủ. Vui lòng thử lại sau.';
  return `Không thể kiểm tra kết nối ${service}. Vui lòng thử lại sau.`;
}
