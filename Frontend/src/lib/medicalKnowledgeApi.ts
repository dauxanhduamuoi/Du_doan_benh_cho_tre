import { ApiError, request } from './api';

export interface DiseaseGroupOption {
  id: string;
  name: string;
}

export interface WeatherFactorOption {
  value: string;
  label_vi: string;
}

export interface MedicalKnowledgeOptions {
  disease_groups: DiseaseGroupOption[];
  weather_factors: WeatherFactorOption[];
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

export interface ServiceConnectionTestResult {
  ok: boolean;
  message: string;
}

export type EvidenceLevel = 'SUPPORTED' | 'LIMITED_OR_INDIRECT' | 'CONFLICTING' | 'INSUFFICIENT';
export type EvidenceScope = 'WHOLE_GROUP' | 'PARTIAL_GROUP';
export type RevisionStatus = 'DRAFT' | 'APPROVED' | 'REJECTED';

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
  source_role: string;
  sort_order: number;
  relevance_note: string | null;
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
}

export interface DraftRevision extends DraftRevisionSummary {
  topic_id: number;
  disease_group_id: string;
  disease_group_name: string;
  weather_factor: string;
  short_explanation_vi: string;
  detailed_explanation_vi: string;
  limitations_vi: string;
  parent_display_allowed: boolean;
  llm_model: string | null;
  prompt_version: string | null;
  created_by: number | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  sources: DraftSource[];
}

export interface DraftTopicHistory {
  topic: {
    id: number;
    disease_group_id: string;
    disease_group_name: string;
    weather_factor: string;
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

export interface PubMedSearchPayload {
  disease_group_id: string;
  weather_factor: string;
  disease_terms: string[];
  max_results: 10 | 15 | 25;
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
}

export interface PubMedSearchResponse {
  disease_group_id: string;
  weather_factor: string;
  query: string;
  count: number;
  results: PubMedPaper[];
}

export interface PubMedImportedSource {
  id: number;
  pmid: string;
  created: boolean;
  title: string;
  retrieved_at: string | null;
}

export interface PubMedImportResponse {
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

export function importPubMedSources(pmids: string[]): Promise<PubMedImportResponse> {
  return request<PubMedImportResponse>('/api/medical-knowledge/pubmed/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pmids }),
  });
}

export function generateMedicalKnowledgeDraft(payload: {
  disease_group_id: string;
  weather_factor: string;
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
  weatherFactor: string,
): Promise<DraftTopicHistory> {
  const query = new URLSearchParams({
    disease_group_id: diseaseGroupId,
    weather_factor: weatherFactor,
  });
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

export function medicalKnowledgeDraftErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn hoặc không hợp lệ.';
    if (error.status === 403) return 'Bạn không có quyền sử dụng chức năng này.';
    if (error.status === 404) return 'Không tìm thấy nhóm bệnh, nguồn hoặc bản nháp được yêu cầu.';
    if (error.status === 409) return 'Chỉ bản nháp ở trạng thái DRAFT mới có thể chỉnh sửa.';
    if (error.status === 429) return 'Đã đạt giới hạn sử dụng nhà cung cấp AI. Hãy thử lại sau.';
    if (error.status === 503) return 'Chức năng tạo bản nháp bằng AI chưa được cấu hình.';
    if (error.status === 502) return 'AI chưa thể tạo bản nháp hợp lệ. Vui lòng thử lại sau.';
    if (error.status === 422) return 'Nguồn hoặc phạm vi tạo bản nháp chưa hợp lệ.';
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
