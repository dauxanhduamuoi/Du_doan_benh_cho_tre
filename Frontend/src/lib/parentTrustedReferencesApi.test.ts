import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import {
  approveParentReference, createParentReferenceDraft, getParentReferenceCuration, getParentReferenceHistory,
  getParentReferenceProofCandidates, listParentReferenceCurations, parentReferenceError, referenceSelector,
  reopenParentReference, revokeParentReference,
} from './parentTrustedReferencesApi';

const BASE = '/api/medical-knowledge/parent-references';
const selector = { disease_group_id: '005', factor_type: 'WEATHER' as const, factor_key: 'humidity', factor_value: null };
const source = { source_id: 42, provider_id: 'WHO', source_type: 'WHO', external_id: '1', source_kind: 'GUIDELINE',
  title: 'Hướng dẫn', journal: 'WHO', publication_year: 2025, original_url: 'https://www.who.int/publications/b/1' };
const state = { approval_id: 71, topic_id: 17, source_id: 42, selector, status: 'DRAFT', version: 3, evidence_content_id: null,
  source_in_library: true, policy_decision: 'UNCERTAIN', policy_reason_code: 'MISSING_TRUST_METADATA',
  created_by: 7, created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00', approved_by: null, approved_at: null,
  revoked_by: null, revoked_at: null, source };
const proof = { evidence_content_id: 500, source_id: 42, content_kind: 'OFFICIAL_SUMMARY_EXCERPT', content_origin: 'WHO_PUBLICATIONS_API',
  external_identifier: '1', retrieved_at: '2026-01-01T00:00:00', content_sha256: 'a'.repeat(64), policy_decision: 'ALLOW_PARENT_REFERENCE', policy_reason_code: 'WHO_OFFICIAL_GUIDANCE' };
const page = { selector, topic_id: 17, source_id: 42, source, candidates: [proof], next_offset: null };
const mutation = { approval_id: 71, status: 'DRAFT', version: 3, evidence_content_id: null, changed: true };
function mock(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  vi.stubGlobal('fetch', fetchMock); localStorage.setItem('sd_token', 'fixture-staff-token'); return fetchMock;
}
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe('authenticated staff Parent Reference client', () => {
  it('preserves exact selector and strips legacy alias from requests', () => {
    expect(referenceSelector('005', { factor_type: 'WEATHER', factor_key: 'humidity', factor_value: null, weather_factor: 'humidity' })).toEqual(selector);
  });
  it.each(['AGE', 'SEX'] as const)('requires exact %s value', type => {
    expect(() => referenceSelector('005', { factor_type: type, factor_key: type === 'AGE' ? 'age_group' : 'gender', factor_value: null })).toThrow();
  });
  it('GET list is authenticated with exact leading-zero ID/NULL semantics', async () => {
    const fetchMock = mock({ selector, topic_id: 17, items: [state] });
    const result = await listParentReferenceCurations(selector);
    expect(result.items[0].version).toBe(3);
    const [path, init] = fetchMock.mock.calls[0]; const url = new URL(path, 'https://local.test');
    expect(url.pathname).toBe(BASE); expect(url.searchParams.get('disease_group_id')).toBe('005');
    expect(url.searchParams.has('factor_value')).toBe(false); expect(url.searchParams.has('weather_factor')).toBe(false);
    expect(init.headers.Authorization).toBe('Bearer fixture-staff-token');
  });
  it.each([['AGE', 'age_group', '1-5 tuổi'], ['SEX', 'gender', 'Nữ'], ['SEASONALITY', 'time_of_year', null]] as const)('sends exact %s factor', async (type, key, value) => {
    const selected = { ...selector, factor_type: type, factor_key: key, factor_value: value };
    const fetchMock = mock({ selector: selected, topic_id: 17, items: [] }); await listParentReferenceCurations(selected);
    const url = new URL(fetchMock.mock.calls[0][0], 'https://local.test');
    expect(url.searchParams.get('factor_value')).toBe(value);
  });
  it('whitelists state/source metadata without generated prose or snapshot', async () => {
    mock({ ...state, identity_snapshot_json: { PRIVATE: true }, short_explanation_vi: 'PRIVATE', raw_metadata_json: { secret: true },
      source: { ...source, password: 'PRIVATE', evidence_text: 'PRIVATE' } });
    const result = await getParentReferenceCuration(71, selector);
    expect(JSON.stringify(result)).not.toContain('PRIVATE'); expect(result).not.toHaveProperty('identity_snapshot_json');
  });
  it.each([null, {}, { ...state, version: 0 }, { ...state, version: '3' }, { ...state, status: 'AUTO_APPROVED' },
    { ...state, approval_id: 72 }, { ...state, selector: { ...selector, disease_group_id: '5' } },
    { ...state, source: { ...source, source_id: 43 } }, { ...state, created_at: 'not-a-date' },
    { ...state, policy_decision: 'TRUSTED' }])('rejects malformed state/identity instead of enabling mutations: %j', async value => {
    mock(value); await expect(getParentReferenceCuration(71, selector)).rejects.toThrow();
  });
  it('rejects duplicate curation identities and mismatched topic', async () => {
    mock({ selector, topic_id: 17, items: [state, state] }); await expect(listParentReferenceCurations(selector)).rejects.toThrow();
    mock({ selector, topic_id: 18, items: [state] }); await expect(listParentReferenceCurations(selector)).rejects.toThrow();
  });
  it('creates DRAFT with only selector/source/note', async () => {
    const fetchMock = mock(mutation); await createParentReferenceDraft(selector, 42, 'Kiểm tra nguồn');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ...selector, source_id: 42, review_note: 'Kiểm tra nguồn' });
  });
  it('approve sends exact proof/current version and no client authority', async () => {
    const fetchMock = mock({ ...mutation, status: 'APPROVED', evidence_content_id: 500 }); await approveParentReference(71, selector, 3, 500);
    expect(fetchMock.mock.calls[0][0]).toBe(BASE + '/71/approve');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ...selector, expected_version: 3, evidence_content_id: 500, review_note: null });
  });
  it.each(['revoke', 'reopen'] as const)('%s sends version/note only', async action => {
    const fetchMock = mock({ ...mutation, status: action === 'revoke' ? 'REVOKED' : 'DRAFT' });
    await (action === 'revoke' ? revokeParentReference : reopenParentReference)(71, 3, 'Ghi chú tiếng Việt');
    expect(fetchMock.mock.calls[0][0]).toBe(BASE + '/71/' + action);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ expected_version: 3, review_note: 'Ghi chú tiếng Việt' });
  });
  it('rejects oversized note before making mutation request', async () => {
    const fetchMock = mock(mutation); await expect(createParentReferenceDraft(selector, 42, 'X'.repeat(1001))).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('rejects mutation responses from a different approval or unexpected transition', async () => {
    mock({ ...mutation, approval_id: 99, status: 'APPROVED', evidence_content_id: 500 });
    await expect(approveParentReference(71, selector, 3, 500)).rejects.toThrow();
    mock({ ...mutation, status: 'APPROVED', evidence_content_id: 501 }); await expect(approveParentReference(71, selector, 3, 500)).rejects.toThrow();
    mock({ ...mutation, evidence_content_id: 500 }); await expect(reopenParentReference(71, 3)).rejects.toThrow();
  });
  it('proof pages use bounded pagination/source and propagate cancellation', async () => {
    const fetchMock = mock(page); const signal = new AbortController().signal;
    await getParentReferenceProofCandidates(selector, 42, 100, signal);
    const url = new URL(fetchMock.mock.calls[0][0], 'https://local.test');
    expect(url.pathname).toBe(BASE + '/proof-candidates'); expect(url.searchParams.get('source_id')).toBe('42');
    expect(url.searchParams.get('offset')).toBe('100'); expect(url.searchParams.get('limit')).toBe('100');
    expect(fetchMock.mock.calls[0][1].signal).toBe(signal);
  });
  it('accepts zero/one/multiple proofs without selection or extra calls', async () => {
    for (const candidates of [[], [proof], [proof, { ...proof, evidence_content_id: 501 }]]) {
      const fetchMock = mock({ ...page, candidates });
      const result = await getParentReferenceProofCandidates(selector, 42);
      expect(result.candidates).toHaveLength(candidates.length); expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(result).not.toHaveProperty('selected_proof');
    }
  });
  it.each(['ALLOW_PARENT_REFERENCE', 'STAFF_ONLY', 'REJECT_PARENT_REFERENCE', 'UNCERTAIN'])('preserves backend policy %s', async decision => {
    mock({ ...page, candidates: [{ ...proof, policy_decision: decision }] });
    expect((await getParentReferenceProofCandidates(selector, 42)).candidates[0].policy_decision).toBe(decision);
  });
  it('strips proof body/provenance/secrets before UI consumes metadata', async () => {
    mock({ ...page, candidates: [{ ...proof, evidence_text: 'PRIVATE', provenance_json: { token: 'PRIVATE' }, generated_prose: 'PRIVATE' }] });
    expect(JSON.stringify(await getParentReferenceProofCandidates(selector, 42))).not.toContain('PRIVATE');
  });
  it.each([{ ...page, source_id: 43 }, { ...page, selector: { ...selector, factor_value: 'null' } },
    { ...page, candidates: [{ ...proof, source_id: 43 }] }, { ...page, candidates: [{ ...proof, evidence_content_id: 0 }] },
    { ...page, candidates: [{ ...proof, content_sha256: 'bad' }] }, { ...page, candidates: [{ ...proof, policy_decision: 'TRUSTED' }] },
    { ...page, candidates: [proof, proof] }, { ...page, next_offset: 0 }, { ...page, next_offset: 99 },
    { ...page, candidates: Array.from({ length: 101 }, (_, i) => ({ ...proof, evidence_content_id: 500 + i })) }])('rejects unsafe proof page identity/bounds: %j', async payload => {
    mock(payload); await expect(getParentReferenceProofCandidates(selector, 42)).rejects.toThrow();
  });
  it.each(['http://evil.example', 'javascript:alert(1)', 'https://user:secret@who.int', 'https://who.int/?token=PRIVATE'])('removes unsafe display URL %s', async url => {
    mock({ ...state, source: { ...source, original_url: url } }); expect((await getParentReferenceCuration(71, selector)).source.original_url).toBeNull();
  });
  it('history validates approval identity, sorts version and strips snapshots', async () => {
    const event = { id: 1, action: 'CREATE_DRAFT', from_status: null, to_status: 'DRAFT', actor_user_id: 7,
      created_at: '2026-01-01T00:00:00', resulting_version: 1, review_note: 'Đã kiểm tra' };
    mock({ approval_id: 71, events: [{ ...event, id: 2, resulting_version: 2, identity_snapshot_json: 'PRIVATE' }, event] });
    const events = await getParentReferenceHistory(71); expect(events.map(item => item.resulting_version)).toEqual([1, 2]);
    expect(events[0].review_note).toBe('Đã kiểm tra'); expect(JSON.stringify(events)).not.toContain('PRIVATE');
    mock({ approval_id: 72, events: [] }); await expect(getParentReferenceHistory(71)).rejects.toThrow();
  });
  it.each([401, 403, 404, 409, 422, 500])('propagates HTTP %i once and redacts raw server error', async status => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ detail: { code: 'PRIVATE', message: 'PRIVATE CREDENTIALS' } }) });
    vi.stubGlobal('fetch', fetchMock);
    let error: unknown; try { await approveParentReference(71, selector, 3, 500); } catch (caught) { error = caught; }
    expect(error).toBeInstanceOf(ApiError); expect(parentReferenceError(error)).not.toContain('PRIVATE'); expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
