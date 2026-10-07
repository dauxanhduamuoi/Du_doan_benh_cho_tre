import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api';
import type { TopicSourceLibrary } from '@/lib/medicalKnowledgeApi';
import type { ProofCandidate, ReferenceEvent, ReferenceState } from '@/lib/parentTrustedReferencesApi';
import ParentReferenceCurationPanel from './ParentReferenceCurationPanel';

const mocks = vi.hoisted(() => ({ role: 'staff' as string | null,
  list: vi.fn(), current: vi.fn(), create: vi.fn(), proofs: vi.fn(), approve: vi.fn(), revoke: vi.fn(), reopen: vi.fn(), history: vi.fn(),
}));
vi.mock('@/app/contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.role === null ? null : { id: 7, role: mocks.role, permissions: [] } }) }));
vi.mock('@/lib/parentTrustedReferencesApi', async original => ({
  ...await original<typeof import('@/lib/parentTrustedReferencesApi')>(),
  listParentReferenceCurations: mocks.list, getParentReferenceCuration: mocks.current, createParentReferenceDraft: mocks.create,
  getParentReferenceProofCandidates: mocks.proofs, approveParentReference: mocks.approve, revokeParentReference: mocks.revoke,
  reopenParentReference: mocks.reopen, getParentReferenceHistory: mocks.history,
}));

const factor = { factor_type: 'WEATHER' as const, factor_key: 'humidity', factor_value: null, weather_factor: 'humidity' };
const selector = { disease_group_id: '005', factor_type: 'WEATHER' as const, factor_key: 'humidity', factor_value: null };
const library: TopicSourceLibrary = { ...factor, disease_group_id: '005', topic_id: 17, sources: [{
  source_id: 42, provider_id: 'WHO', title: 'Hướng dẫn WHO', journal: 'WHO', publication_year: 2025, pmid: null, doi: null,
  pmcid: null, content_kind: null, usable_for_draft: false, added_at: '2026-01-01T00:00:00',
}] };
const sourceMetadata = { source_id: 42, provider_id: 'WHO', source_type: 'WHO', external_id: '1', source_kind: 'GUIDELINE',
  title: 'Hướng dẫn WHO', journal: 'WHO', publication_year: 2025, original_url: 'https://www.who.int/publications/b/1' };
function state(status: ReferenceState['status'] = 'DRAFT', version = 1): ReferenceState {
  return { approval_id: 71, topic_id: 17, source_id: 42, selector, status, version, evidence_content_id: status === 'DRAFT' ? null : 500,
    source_in_library: true, policy_decision: status === 'DRAFT' ? 'UNCERTAIN' : 'ALLOW_PARENT_REFERENCE', policy_reason_code: 'MISSING_TRUST_METADATA',
    created_by: 7, created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
    approved_by: status === 'DRAFT' ? null : 7, approved_at: status === 'DRAFT' ? null : '2026-01-02T00:00:00',
    revoked_by: status === 'REVOKED' ? 7 : null, revoked_at: status === 'REVOKED' ? '2026-01-03T00:00:00' : null, source: sourceMetadata };
}
function proof(id = 500, decision: ProofCandidate['policy_decision'] = 'ALLOW_PARENT_REFERENCE'): ProofCandidate {
  return { evidence_content_id: id, source_id: 42, content_kind: 'OFFICIAL_SUMMARY_EXCERPT', content_origin: 'WHO_PUBLICATIONS_API',
    external_identifier: '1', retrieved_at: '2026-01-01T00:00:00', content_sha256: 'a'.repeat(64), policy_decision: decision, policy_reason_code: 'WHO_OFFICIAL_GUIDANCE' };
}
function page(candidates = [proof()], next_offset: number | null = null) { return { selector, topic_id: 17, source_id: 42, source: sourceMetadata, candidates, next_offset }; }
function result(item: ReferenceState) { return { approval_id: item.approval_id, status: item.status, version: item.version, evidence_content_id: item.evidence_content_id, changed: true }; }
let persisted: ReferenceState[];
const props = { diseaseGroupId: '005', factor, library, loading: false };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function ready(item?: ReferenceState) {
  persisted = item ? [item] : [];
  const view = render(<ParentReferenceCurationPanel {...props} />);
  await screen.findByRole('article', { name: 'Duyệt nguồn 42' });
  return view;
}
async function openProofs() {
  fireEvent.click(screen.getByRole('button', { name: 'Chọn bằng chứng xác minh' }));
  await waitFor(() => expect(screen.queryByText('Đang tải bằng chứng…')).not.toBeInTheDocument());
}
const approveButton = () => screen.getByRole('button', { name: 'Duyệt và hiển thị cho phụ huynh' });

beforeEach(() => {
  mocks.role = 'staff'; persisted = [];
  for (const mock of [mocks.list, mocks.current, mocks.create, mocks.proofs, mocks.approve, mocks.revoke, mocks.reopen, mocks.history]) mock.mockReset();
  mocks.list.mockImplementation(async (requested) => ({ topic_id: 17, selector: requested, items: persisted }));
  mocks.current.mockImplementation(async (id) => persisted.find(item => item.approval_id === id));
  mocks.create.mockImplementation(async () => { persisted = [state()]; return result(persisted[0]); });
  mocks.proofs.mockResolvedValue(page());
  mocks.approve.mockImplementation(async () => { persisted = [state('APPROVED', 2)]; return result(persisted[0]); });
  mocks.revoke.mockImplementation(async () => { persisted = [state('REVOKED', 3)]; return result(persisted[0]); });
  mocks.reopen.mockImplementation(async () => { persisted = [state('DRAFT', 4)]; return result(persisted[0]); });
  mocks.history.mockResolvedValue([]);
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Unexpected network'); }));
});
afterEach(() => vi.unstubAllGlobals());

describe('staff Parent Reference Curation', () => {
  it.each(['staff', 'admin'])('renders for %s with library/AI/curation boundaries', async role => {
    mocks.role = role; await ready();
    expect(screen.getByText(/Trong kho nguồn của chủ đề/)).toBeInTheDocument();
    expect(screen.getByText(/AI Draft: Chỉ lưu để tham khảo/)).toBeInTheDocument();
    expect(screen.getByText(/Phụ huynh: Chưa duyệt/)).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith(selector, expect.any(AbortSignal));
    expect(mocks.proofs).not.toHaveBeenCalled(); expect(mocks.history).not.toHaveBeenCalled();
  });
  it.each(['parent', 'viewer', null])('hides from unauthorized role %s', role => {
    mocks.role = role; render(<ParentReferenceCurationPanel {...props} />);
    expect(screen.queryByRole('region')).not.toBeInTheDocument(); expect(mocks.list).not.toHaveBeenCalled();
  });
  it('handles empty source library without API calls', () => {
    render(<ParentReferenceCurationPanel {...props} library={{ ...library, sources: [] }} />);
    expect(screen.getByText(/Chủ đề chưa có nguồn/)).toBeInTheDocument(); expect(mocks.list).not.toHaveBeenCalled();
  });
  it('does not attach a library from another selector', () => {
    render(<ParentReferenceCurationPanel {...props} diseaseGroupId="006" />);
    expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(mocks.list).not.toHaveBeenCalled();
  });
  it.each([['AGE', 'age_group', '1-5 tuổi'], ['SEX', 'gender', 'Nữ'], ['SEASONALITY', 'time_of_year', null]] as const)('preserves exact %s selector', async (type, key, value) => {
    const selectedFactor = { factor_type: type, factor_key: key, factor_value: value };
    render(<ParentReferenceCurationPanel {...props} factor={selectedFactor} library={{ ...library, ...selectedFactor }} />);
    await screen.findByRole('article');
    expect(mocks.list).toHaveBeenCalledWith({ disease_group_id: '005', ...selectedFactor }, expect.any(AbortSignal));
  });
  it('creates DRAFT with note, exact selector/source and no auto approve', async () => {
    await ready();
    fireEvent.change(screen.getByLabelText(/Ghi chú duyệt nguồn/), { target: { value: 'Đã kiểm tra nguồn tiếng Việt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Bắt đầu duyệt cho phụ huynh' }));
    await screen.findByText('Phụ huynh: Đang xem xét');
    expect(mocks.create).toHaveBeenCalledWith(selector, 42, 'Đã kiểm tra nguồn tiếng Việt', expect.any(AbortSignal));
    expect(mocks.current).toHaveBeenCalledWith(71, selector, expect.any(AbortSignal));
    expect(mocks.approve).not.toHaveBeenCalled(); expect(mocks.proofs).not.toHaveBeenCalled();
  });
  it('bounds notes to 1000 characters', async () => {
    await ready(); fireEvent.change(screen.getByLabelText(/Ghi chú duyệt nguồn/), { target: { value: 'X'.repeat(1001) } });
    expect(screen.getByLabelText(/Ghi chú duyệt nguồn/)).toHaveValue('X'.repeat(1000));
  });
  it('shows DRAFT and fetches proof on demand with exact source', async () => {
    await ready(state()); expect(screen.queryByText(/Phụ huynh: Đang hiển thị/)).not.toBeInTheDocument();
    expect(mocks.proofs).not.toHaveBeenCalled(); await openProofs();
    expect(mocks.proofs).toHaveBeenCalledWith(selector, 42, 0, expect.any(AbortSignal));
    expect(screen.getByText(/WHO_PUBLICATIONS_API/)).toBeInTheDocument(); expect(screen.getByText('WHO_OFFICIAL_GUIDANCE')).toBeInTheDocument();
  });
  it('zero candidates disables approve', async () => {
    mocks.proofs.mockResolvedValue(page([])); await ready(state()); await openProofs();
    expect(screen.getByText(/Chưa có bằng chứng xác minh/)).toBeInTheDocument(); expect(approveButton()).toBeDisabled();
  });
  it.each([1, 3])('%i candidates do not select or approve automatically', async count => {
    mocks.proofs.mockResolvedValue(page(Array.from({ length: count }, (_, i) => proof(500 + i))));
    await ready(state()); await openProofs();
    expect(screen.getAllByRole('radio')).toHaveLength(count);
    expect(screen.getAllByRole('radio').every(radio => !(radio as HTMLInputElement).checked)).toBe(true);
    expect(approveButton()).toBeDisabled(); expect(mocks.approve).not.toHaveBeenCalled();
  });
  it.each(['ALLOW_PARENT_REFERENCE', 'STAFF_ONLY', 'REJECT_PARENT_REFERENCE', 'UNCERTAIN'] as const)('uses backend candidate decision %s', async decision => {
    mocks.proofs.mockResolvedValue(page([proof(500, decision)])); await ready(state()); await openProofs();
    fireEvent.click(screen.getByRole('radio', { name: 'Chọn bằng chứng #500' }));
    if (decision === 'ALLOW_PARENT_REFERENCE') expect(approveButton()).toBeEnabled(); else expect(approveButton()).toBeDisabled();
  });
  it('missing membership disables approve even for an ALLOW proof', async () => {
    await ready({ ...state(), source_in_library: false }); await openProofs();
    fireEvent.click(screen.getByRole('radio')); expect(approveButton()).toBeDisabled();
  });
  it('approves explicit proof id with current version, independent of AI eligibility', async () => {
    mocks.proofs.mockResolvedValue(page([proof(500), proof(501)])); await ready(state('DRAFT', 8)); await openProofs();
    fireEvent.click(screen.getByRole('radio', { name: 'Chọn bằng chứng #501' })); fireEvent.click(approveButton());
    await screen.findByText('Phụ huynh: Đang hiển thị cho phụ huynh');
    expect(mocks.approve).toHaveBeenCalledWith(71, selector, 8, 501, '', expect.any(AbortSignal));
  });
  it('requires revoke confirmation and preserves library source', async () => {
    await ready(state('APPROVED', 2)); fireEvent.click(screen.getByRole('button', { name: 'Thu hồi khỏi phụ huynh' }));
    expect(mocks.revoke).not.toHaveBeenCalled(); fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Hủy' }));
    expect(mocks.revoke).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Thu hồi khỏi phụ huynh' }));
    fireEvent.click(screen.getByRole('button', { name: 'Xác nhận thu hồi' })); await screen.findByText('Phụ huynh: Đã thu hồi');
    expect(mocks.revoke).toHaveBeenCalledWith(71, 2, '', expect.any(AbortSignal)); expect(screen.getByRole('article')).toBeInTheDocument();
  });
  it('reopen resets proof review and reapproval requires a new explicit selection', async () => {
    await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('radio')); fireEvent.click(approveButton());
    await screen.findByText('Phụ huynh: Đang hiển thị cho phụ huynh');
    fireEvent.click(screen.getByRole('button', { name: 'Thu hồi khỏi phụ huynh' })); fireEvent.click(screen.getByRole('button', { name: 'Xác nhận thu hồi' }));
    await screen.findByText('Phụ huynh: Đã thu hồi'); fireEvent.click(screen.getByRole('button', { name: 'Mở lại để duyệt' }));
    await screen.findByText('Phụ huynh: Đang xem xét'); expect(mocks.reopen).toHaveBeenCalledWith(71, 3, '', expect.any(AbortSignal));
    expect(screen.queryByRole('radio')).not.toBeInTheDocument(); await openProofs();
    expect(screen.getByRole('radio')).not.toBeChecked(); expect(approveButton()).toBeDisabled();
    expect(mocks.proofs).toHaveBeenCalledTimes(2);
  });
  it('409 refreshes current/list and clears selection without retrying mutation', async () => {
    await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('radio'));
    mocks.approve.mockImplementation(async () => { persisted = [state('DRAFT', 9)]; throw new ApiError(409, 'CONCURRENT'); });
    fireEvent.click(approveButton()); await screen.findByText('Phiên bản duyệt: 9');
    expect(screen.getByRole('alert')).toHaveTextContent('Dữ liệu đã được thay đổi bởi thao tác khác');
    expect(mocks.approve).toHaveBeenCalledTimes(1); expect(mocks.current).toHaveBeenCalledWith(71, selector, expect.any(AbortSignal));
    await openProofs(); expect(screen.getByRole('radio')).not.toBeChecked(); expect(approveButton()).toBeDisabled();
  });
  it('409 clears proof even if persisted version is unchanged', async () => {
    await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('radio'));
    mocks.approve.mockRejectedValue(new ApiError(409, 'CONFLICT')); fireEvent.click(approveButton());
    await screen.findByRole('button', { name: 'Chọn bằng chứng xác minh' }); await openProofs(); expect(approveButton()).toBeDisabled();
  });
  it('create conflict refreshes existing curation without duplicate POST', async () => {
    await ready(); mocks.create.mockImplementation(async () => { persisted = [state()]; throw new ApiError(409, 'EXISTS'); });
    fireEvent.click(screen.getByRole('button', { name: 'Bắt đầu duyệt cho phụ huynh' })); await screen.findByText('Phụ huynh: Đang xem xét');
    expect(mocks.create).toHaveBeenCalledTimes(1);
  });
  it('shows history on demand including Vietnamese note and actor/version', async () => {
    const event: ReferenceEvent = { id: 1, action: 'CREATE_DRAFT', from_status: null, to_status: 'DRAFT', actor_user_id: 7,
      created_at: '2026-01-01T00:00:00', resulting_version: 1, review_note: 'Đã rà soát, cần kiểm tra thêm' };
    mocks.history.mockResolvedValue([event]); await ready(state()); fireEvent.click(screen.getByRole('button', { name: 'Lịch sử duyệt' }));
    await screen.findByText(event.review_note!); expect(mocks.history).toHaveBeenCalledWith(71, expect.any(AbortSignal));
    expect(screen.getByText(/Bắt đầu xem xét · Phiên bản 1/)).toBeInTheDocument();
  });
  it('supports empty history', async () => {
    await ready(state()); fireEvent.click(screen.getByRole('button', { name: 'Lịch sử duyệt' })); await screen.findByText('Chưa có lịch sử duyệt.');
  });
  it.each(['list', 'proofs', 'history', 'create'] as const)('isolates %s errors and supports explicit retry', async operation => {
    if (operation === 'list') {
      mocks.list.mockRejectedValueOnce(new ApiError(503, 'PRIVATE')); render(<ParentReferenceCurationPanel {...props} />);
    } else {
      await ready(operation === 'create' ? undefined : state()); mocks[operation].mockRejectedValueOnce(new ApiError(503, 'PRIVATE'));
      fireEvent.click(screen.getByRole('button', { name: operation === 'proofs' ? 'Chọn bằng chứng xác minh' : operation === 'history' ? 'Lịch sử duyệt' : 'Bắt đầu duyệt cho phụ huynh' }));
    }
    await screen.findByRole('alert'); expect(screen.queryByText('PRIVATE')).not.toBeInTheDocument();
    if (operation === 'list') { fireEvent.click(screen.getByRole('button', { name: 'Tải lại trạng thái duyệt' })); await screen.findByRole('article'); }
    else expect(await screen.findByRole('article')).toBeInTheDocument();
  });
  it('loads subsequent pages, deduplicates and selects a later-page proof', async () => {
    mocks.proofs.mockResolvedValueOnce(page([proof()], 100)).mockResolvedValueOnce(page([proof(), proof(600)]));
    await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('button', { name: 'Tải thêm bằng chứng' }));
    await screen.findByRole('radio', { name: 'Chọn bằng chứng #600' }); expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(mocks.proofs).toHaveBeenLastCalledWith(selector, 42, 100, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole('radio', { name: 'Chọn bằng chứng #600' })); fireEvent.click(approveButton());
    await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith(71, selector, 1, 600, '', expect.any(AbortSignal)));
  });
  it('blocks stale curation responses after selector change', async () => {
    const old = deferred<{ topic_id: number; selector: typeof selector; items: ReferenceState[] }>(); mocks.list.mockReturnValueOnce(old.promise);
    const view = render(<ParentReferenceCurationPanel {...props} />);
    const otherLibrary = { ...library, disease_group_id: '006', topic_id: 18, sources: [{ ...library.sources[0], source_id: 43 }] };
    mocks.list.mockResolvedValue({ topic_id: 18, selector: { ...selector, disease_group_id: '006' }, items: [] });
    view.rerender(<ParentReferenceCurationPanel {...props} diseaseGroupId="006" library={otherLibrary} />);
    await screen.findByRole('article', { name: 'Duyệt nguồn 43' });
    await act(async () => old.resolve({ topic_id: 17, selector, items: [state('APPROVED', 2)] }));
    expect(screen.queryByRole('article', { name: 'Duyệt nguồn 42' })).not.toBeInTheDocument();
    expect(screen.queryByText('Phụ huynh: Đang hiển thị cho phụ huynh')).not.toBeInTheDocument();
  });
  it.each(['proofs', 'history', 'approve'] as const)('ignores old %s response and mutation refresh after selector change', async kind => {
    const old = deferred<unknown>(); const view = await ready(state());
    if (kind === 'approve') { await openProofs(); fireEvent.click(screen.getByRole('radio')); mocks.approve.mockReturnValueOnce(old.promise); fireEvent.click(approveButton()); }
    else { mocks[kind].mockReturnValueOnce(old.promise); fireEvent.click(screen.getByRole('button', { name: kind === 'proofs' ? 'Chọn bằng chứng xác minh' : 'Lịch sử duyệt' })); }
    const otherLibrary = { ...library, disease_group_id: '006', topic_id: 18, sources: [{ ...library.sources[0], source_id: 43 }] };
    mocks.list.mockResolvedValue({ topic_id: 18, selector: { ...selector, disease_group_id: '006' }, items: [] });
    // Rerender the mounted root, not another panel instance.
    view.rerender(<ParentReferenceCurationPanel {...props} diseaseGroupId="006" library={otherLibrary} />);
    await screen.findByRole('article', { name: 'Duyệt nguồn 43' });
    await act(async () => old.resolve(kind === 'proofs' ? page([proof(999)]) : kind === 'history' ? [{ id: 1, action: 'APPROVE', review_note: 'OLD HISTORY' }] : result(state('APPROVED', 2))));
    expect(screen.queryByRole('radio')).not.toBeInTheDocument(); expect(screen.queryByText('OLD HISTORY')).not.toBeInTheDocument();
    expect(mocks.current).not.toHaveBeenCalled();
  });
  it('resets candidates/selection/pagination on selector change', async () => {
    mocks.proofs.mockResolvedValue(page([proof()], 100)); const view = await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('radio'));
    const other = { ...library, factor_key: 'temperature', weather_factor: 'temperature' };
    persisted = [{ ...state(), selector: { ...selector, factor_key: 'temperature' } }];
    view.rerender(<ParentReferenceCurationPanel {...props} factor={{ ...factor, factor_key: 'temperature', weather_factor: 'temperature' }} library={other} />);
    await screen.findByRole('button', { name: 'Chọn bằng chứng xác minh' });
    expect(screen.queryByRole('radio')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Tải thêm bằng chứng' })).not.toBeInTheDocument();
  });
  it('old history cannot attach to another source in the same topic', async () => {
    const old = deferred<ReferenceEvent[]>(); mocks.history.mockReturnValueOnce(old.promise);
    const view = await ready(state()); fireEvent.click(screen.getByRole('button', { name: 'Lịch sử duyệt' }));
    persisted = [{ ...state(), approval_id: 72, source_id: 43, source: { ...sourceMetadata, source_id: 43 } }];
    view.rerender(<ParentReferenceCurationPanel {...props} library={{ ...library, sources: [{ ...library.sources[0], source_id: 43 }] }} />);
    await screen.findByRole('article', { name: 'Duyệt nguồn 43' });
    await act(async () => old.resolve([{ id: 1, action: 'CREATE_DRAFT', from_status: null, to_status: 'DRAFT', actor_user_id: 7,
      created_at: '2026-01-01T00:00:00', resulting_version: 1, review_note: 'OLD SOURCE HISTORY' }]));
    expect(screen.queryByText('OLD SOURCE HISTORY')).not.toBeInTheDocument(); expect(mocks.history).toHaveBeenCalledTimes(1);
  });
  it('pending next-page response is ignored after selector change', async () => {
    const old = deferred<ReturnType<typeof page>>();
    mocks.proofs.mockResolvedValueOnce(page([proof()], 100)).mockReturnValueOnce(old.promise);
    const view = await ready(state()); await openProofs(); fireEvent.click(screen.getByRole('button', { name: 'Tải thêm bằng chứng' }));
    const factor2 = { ...factor, factor_key: 'temperature', weather_factor: 'temperature' };
    persisted = [{ ...state(), selector: { ...selector, factor_key: 'temperature' } }];
    view.rerender(<ParentReferenceCurationPanel {...props} factor={factor2} library={{ ...library, ...factor2 }} />);
    await screen.findByRole('button', { name: 'Chọn bằng chứng xác minh' });
    await act(async () => old.resolve(page([proof(600)])));
    expect(screen.queryByRole('radio')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Tải thêm bằng chứng' })).not.toBeInTheDocument();
  });
  it('prevents duplicate create while a mutation is pending', async () => {
    const pending = deferred<ReturnType<typeof result>>(); mocks.create.mockReturnValueOnce(pending.promise);
    await ready(); const button = screen.getByRole('button', { name: 'Bắt đầu duyệt cho phụ huynh' });
    fireEvent.click(button); fireEvent.click(button); expect(mocks.create).toHaveBeenCalledTimes(1);
    persisted = [state()]; await act(async () => pending.resolve(result(state())));
    await screen.findByText('Phụ huynh: Đang xem xét');
  });
});
