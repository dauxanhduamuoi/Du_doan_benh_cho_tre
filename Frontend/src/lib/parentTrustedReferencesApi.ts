import { ApiError, request } from './api';
import { factorIsComplete, type MedicalFactorSelector } from './medicalKnowledgeFactors';

const BASE = '/api/medical-knowledge/parent-references';
export type ReferenceSelector = Pick<MedicalFactorSelector, 'factor_type' | 'factor_key' | 'factor_value'> & { disease_group_id: string };
export type CurationStatus = 'DRAFT' | 'APPROVED' | 'REVOKED';
export type ReferencePolicy = 'ALLOW_PARENT_REFERENCE' | 'STAFF_ONLY' | 'REJECT_PARENT_REFERENCE' | 'UNCERTAIN';
export interface ReferenceSource {
  source_id: number; provider_id: string | null; source_type: string; external_id: string | null;
  source_kind: string | null; title: string; journal: string | null; publication_year: number | null; original_url: string | null;
}
export interface ReferenceState {
  approval_id: number; topic_id: number; source_id: number; selector: ReferenceSelector;
  status: CurationStatus; version: number; evidence_content_id: number | null; source_in_library: boolean;
  policy_decision: ReferencePolicy; policy_reason_code: string;
  created_by: number | null; created_at: string; updated_at: string;
  approved_by: number | null; approved_at: string | null; revoked_by: number | null; revoked_at: string | null;
  source: ReferenceSource;
}
export interface ReferenceMutation {
  approval_id: number; status: CurationStatus; version: number; evidence_content_id: number | null; changed: boolean;
}
export interface ProofCandidate {
  evidence_content_id: number; source_id: number; content_kind: string; content_origin: string;
  external_identifier: string | null; retrieved_at: string; content_sha256: string;
  policy_decision: ReferencePolicy; policy_reason_code: string;
}
export interface ProofPage {
  selector: ReferenceSelector; topic_id: number; source_id: number; source: ReferenceSource;
  candidates: ProofCandidate[]; next_offset: number | null;
}
export interface ReferenceEvent {
  id: number; action: 'CREATE_DRAFT' | 'APPROVE' | 'REVOKE' | 'REOPEN_DRAFT' | 'UPDATE_DRAFT';
  from_status: CurationStatus | null; to_status: CurationStatus; actor_user_id: number | null;
  created_at: string; resulting_version: number; review_note: string | null;
}

// Mutation data must fail closed on malformed identity/version. These parsers
// return whitelisted metadata only, never arbitrary prose/provenance/snapshots.
function invalid(): never { throw new Error('Dữ liệu duyệt nguồn không hợp lệ. Vui lòng tải lại trạng thái.'); }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
function integer(value: unknown, minimum = 1): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) return invalid();
  return value;
}
function text(value: unknown): string { return typeof value === 'string' ? value : invalid(); }
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function nullableId(value: unknown): number | null { return value === null ? null : integer(value); }
function boolean(value: unknown): boolean { return typeof value === 'boolean' ? value : invalid(); }
function date(value: unknown): string {
  const result = text(value);
  return result && Number.isFinite(Date.parse(result)) ? result : invalid();
}
function nullableDate(value: unknown): string | null { return value === null ? null : date(value); }
function choice<T extends string>(value: unknown, values: readonly T[]): T {
  return typeof value === 'string' && values.includes(value as T) ? value as T : invalid();
}
function status(value: unknown): CurationStatus { return choice(value, ['DRAFT', 'APPROVED', 'REVOKED']); }
function policy(value: unknown): ReferencePolicy {
  return choice(value, ['ALLOW_PARENT_REFERENCE', 'STAFF_ONLY', 'REJECT_PARENT_REFERENCE', 'UNCERTAIN']);
}
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : invalid(); }

export function referenceSelector(diseaseGroupId: string, factor: MedicalFactorSelector): ReferenceSelector {
  if (!/^[0-9]{1,6}$/.test(diseaseGroupId) || !factorIsComplete(factor)) return invalid();
  return { disease_group_id: diseaseGroupId, factor_type: factor.factor_type, factor_key: factor.factor_key, factor_value: factor.factor_value };
}
function parseSelector(value: unknown, expected: ReferenceSelector): ReferenceSelector {
  const record = object(value);
  for (const key of ['disease_group_id', 'factor_type', 'factor_key', 'factor_value'] as const) {
    if (record[key] !== expected[key]) return invalid();
  }
  return { ...expected };
}
function safeUrl(value: unknown): string | null {
  if (value === null) return null;
  const raw = text(value);
  if (raw.length > 2048 || /\s/.test(raw) || !/^https:\/\//i.test(raw)) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search) return null;
    url.hash = '';
    return url.href;
  } catch { return null; }
}
function source(value: unknown, expectedId: number): ReferenceSource {
  const data = object(value);
  if (integer(data.source_id) !== expectedId) return invalid();
  return {
    source_id: expectedId, provider_id: nullableText(data.provider_id), source_type: text(data.source_type),
    external_id: nullableText(data.external_id), source_kind: nullableText(data.source_kind), title: text(data.title),
    journal: nullableText(data.journal), publication_year: data.publication_year === null ? null : integer(data.publication_year),
    original_url: safeUrl(data.original_url),
  };
}
function state(value: unknown, expected: ReferenceSelector): ReferenceState {
  const data = object(value);
  const sourceId = integer(data.source_id);
  return {
    approval_id: integer(data.approval_id), topic_id: integer(data.topic_id), source_id: sourceId,
    selector: parseSelector(data.selector, expected), status: status(data.status), version: integer(data.version),
    evidence_content_id: nullableId(data.evidence_content_id), source_in_library: boolean(data.source_in_library),
    policy_decision: policy(data.policy_decision), policy_reason_code: text(data.policy_reason_code),
    created_by: nullableId(data.created_by), created_at: date(data.created_at), updated_at: date(data.updated_at),
    approved_by: nullableId(data.approved_by), approved_at: nullableDate(data.approved_at),
    revoked_by: nullableId(data.revoked_by), revoked_at: nullableDate(data.revoked_at), source: source(data.source, sourceId),
  };
}
function mutation(value: unknown, expectedId?: number): ReferenceMutation {
  const data = object(value);
  const id = integer(data.approval_id);
  if (expectedId !== undefined && id !== expectedId) return invalid();
  return { approval_id: id, status: status(data.status), version: integer(data.version),
    evidence_content_id: nullableId(data.evidence_content_id), changed: boolean(data.changed) };
}
function query(selector: ReferenceSelector): URLSearchParams {
  const params = new URLSearchParams({ disease_group_id: selector.disease_group_id, factor_type: selector.factor_type, factor_key: selector.factor_key });
  if (selector.factor_value !== null) params.set('factor_value', selector.factor_value);
  return params;
}
function note(value?: string): string | null {
  if (value !== undefined && (typeof value !== 'string' || value.length > 1000)) return invalid();
  return value?.trim() || null;
}
async function post(path: string, payload: object, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal });
}
export async function listParentReferenceCurations(selector: ReferenceSelector, signal?: AbortSignal) {
  const data = object(await request<unknown>(`${BASE}?${query(selector)}`, { signal }));
  parseSelector(data.selector, selector);
  const topicId = integer(data.topic_id);
  const items = list(data.items).map(item => state(item, selector));
  const identities = new Set<number>();
  for (const item of items) {
    if (item.topic_id !== topicId || identities.has(item.source_id)) return invalid();
    identities.add(item.source_id);
  }
  return { topic_id: topicId, selector: { ...selector }, items };
}
export async function getParentReferenceCuration(id: number, selector: ReferenceSelector, signal?: AbortSignal): Promise<ReferenceState> {
  const result = state(await request<unknown>(`${BASE}/${integer(id)}`, { signal }), selector);
  return result.approval_id === id ? result : invalid();
}
export async function createParentReferenceDraft(selector: ReferenceSelector, sourceId: number, reviewNote?: string, signal?: AbortSignal) {
  const result = mutation(await post(BASE, { ...selector, source_id: integer(sourceId), review_note: note(reviewNote) }, signal));
  return result.status === 'DRAFT' && result.evidence_content_id === null ? result : invalid();
}
export async function getParentReferenceProofCandidates(selector: ReferenceSelector, sourceId: number, offset = 0, signal?: AbortSignal): Promise<ProofPage> {
  const params = query(selector);
  params.set('source_id', String(integer(sourceId))); params.set('offset', String(integer(offset, 0))); params.set('limit', '100');
  const data = object(await request<unknown>(`${BASE}/proof-candidates?${params}`, { signal }));
  if (integer(data.source_id) !== sourceId) return invalid();
  const candidates = list(data.candidates).map(value => {
    const item = object(value);
    if (integer(item.source_id) !== sourceId || !/^[a-f0-9]{64}$/i.test(text(item.content_sha256))) return invalid();
    return { evidence_content_id: integer(item.evidence_content_id), source_id: sourceId,
      content_kind: text(item.content_kind), content_origin: text(item.content_origin), external_identifier: nullableText(item.external_identifier),
      retrieved_at: date(item.retrieved_at), content_sha256: text(item.content_sha256),
      policy_decision: policy(item.policy_decision), policy_reason_code: text(item.policy_reason_code) };
  });
  const nextOffset = data.next_offset === null ? null : integer(data.next_offset, 0);
  if (candidates.length > 100 || new Set(candidates.map(item => item.evidence_content_id)).size !== candidates.length
      || (nextOffset !== null && nextOffset !== offset + 100)) return invalid();
  return { selector: parseSelector(data.selector, selector), topic_id: integer(data.topic_id), source_id: sourceId,
    source: source(data.source, sourceId), candidates, next_offset: nextOffset };
}
export async function approveParentReference(id: number, selector: ReferenceSelector, version: number, proofId: number, reviewNote?: string, signal?: AbortSignal) {
  const result = mutation(await post(`${BASE}/${integer(id)}/approve`, { ...selector,
    expected_version: integer(version), evidence_content_id: integer(proofId), review_note: note(reviewNote) }, signal), id);
  return result.status === 'APPROVED' && result.evidence_content_id === proofId ? result : invalid();
}
async function versionAction(id: number, action: 'revoke' | 'reopen', version: number, reviewNote?: string, signal?: AbortSignal) {
  const result = mutation(await post(`${BASE}/${integer(id)}/${action}`, { expected_version: integer(version), review_note: note(reviewNote) }, signal), id);
  return result.status === (action === 'revoke' ? 'REVOKED' : 'DRAFT') && (action !== 'reopen' || result.evidence_content_id === null) ? result : invalid();
}
export const revokeParentReference = (id: number, version: number, reviewNote?: string, signal?: AbortSignal) => versionAction(id, 'revoke', version, reviewNote, signal);
export const reopenParentReference = (id: number, version: number, reviewNote?: string, signal?: AbortSignal) => versionAction(id, 'reopen', version, reviewNote, signal);
export async function getParentReferenceHistory(id: number, signal?: AbortSignal): Promise<ReferenceEvent[]> {
  const data = object(await request<unknown>(`${BASE}/${integer(id)}/history`, { signal }));
  if (integer(data.approval_id) !== id) return invalid();
  const events = list(data.events).map(value => {
    const item = object(value);
    return { id: integer(item.id), action: choice(item.action, ['CREATE_DRAFT', 'APPROVE', 'REVOKE', 'REOPEN_DRAFT', 'UPDATE_DRAFT'] as const),
      from_status: item.from_status === null ? null : status(item.from_status), to_status: status(item.to_status),
      actor_user_id: nullableId(item.actor_user_id), created_at: date(item.created_at), resulting_version: integer(item.resulting_version),
      review_note: nullableText(item.review_note) };
  }).sort((a, b) => a.resulting_version - b.resulting_version || a.id - b.id);
  if (new Set(events.map(item => item.resulting_version)).size !== events.length) return invalid();
  return events;
}
export function parentReferenceError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'Dữ liệu đã được thay đổi bởi thao tác khác. Trạng thái mới nhất sẽ được tải lại.';
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
    if (error.status === 403) return 'Bạn không có quyền duyệt nguồn cho phụ huynh.';
    if (error.status === 404) return 'Không tìm thấy chủ đề, nguồn hoặc trạng thái duyệt. Vui lòng tải lại.';
    if (error.status === 422) return 'Nguồn hoặc bằng chứng chưa đáp ứng điều kiện duyệt. Vui lòng kiểm tra lại.';
  }
  return 'Không thể tải hoặc cập nhật duyệt nguồn lúc này. Vui lòng thử tải lại trạng thái.';
}
