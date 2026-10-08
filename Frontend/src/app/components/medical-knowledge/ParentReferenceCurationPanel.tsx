import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useAuth } from '@/app/contexts/AuthContext';
import { canAccessTab } from '@/app/navigation';
import { factorTopicKey, type MedicalFactorSelector } from '@/lib/medicalKnowledgeFactors';
import type { TopicSourceLibrary, TopicSourceLibraryItem } from '@/lib/medicalKnowledgeApi';
import {
  approveParentReference, createParentReferenceDraft, getParentReferenceCuration, getParentReferenceHistory,
  getParentReferenceProofCandidates, listParentReferenceCurations, parentReferenceError, referenceSelector,
  reopenParentReference, revokeParentReference,
  type ProofCandidate, type ReferenceEvent, type ReferencePolicy, type ReferenceSelector, type ReferenceState,
} from '@/lib/parentTrustedReferencesApi';

const POLICY_LABEL: Record<ReferencePolicy, string> = {
  ALLOW_PARENT_REFERENCE: 'Có thể xem xét để hiển thị cho phụ huynh', STAFF_ONLY: 'Chỉ dành cho Staff',
  REJECT_PARENT_REFERENCE: 'Không được phép hiển thị cho phụ huynh', UNCERTAIN: 'Chưa đủ điều kiện',
};
const STATUS_LABEL = { DRAFT: 'Đang xem xét', APPROVED: 'Đang hiển thị cho phụ huynh', REVOKED: 'Đã thu hồi' };
const ACTION_LABEL = { CREATE_DRAFT: 'Bắt đầu xem xét', APPROVE: 'Duyệt', REVOKE: 'Thu hồi', REOPEN_DRAFT: 'Mở lại để duyệt', UPDATE_DRAFT: 'Cập nhật bản xem xét' };
const buttonStyle = 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50';
type Operation = 'create' | 'approve' | 'revoke' | 'reopen';
interface Props { diseaseGroupId: string; factor: MedicalFactorSelector; library: TopicSourceLibrary | null; loading: boolean; children?: ReactNode }

export default function ParentReferenceCurationPanel(props: Props) {
  const { user } = useAuth();
  if (!canAccessTab(user, 'medical-knowledge')) return null;
  const selector = referenceSelector(props.diseaseGroupId, props.factor);
  const library = props.library;
  const matches = library && factorTopicKey(library.disease_group_id, library) === factorTopicKey(props.diseaseGroupId, props.factor);
  return <section aria-label="Duyệt nguồn tham khảo cho phụ huynh" className="space-y-6">
    {props.loading || !matches || !library.topic_id || library.sources.length === 0 ? <>
      <section aria-label="Nguồn đang hiển thị cho phụ huynh" className="border-b border-slate-200 pb-5">
        <h2 className="text-lg font-semibold text-slate-900">Nguồn đang hiển thị cho phụ huynh</h2>
        {props.loading || !matches ? <p role="status" className="mt-2 text-sm text-slate-600">{props.loading ? 'Đang tải kho nguồn của chủ đề…' : 'Kho nguồn của chủ đề chưa sẵn sàng. Vui lòng tải lại kho nguồn.'}</p>
          : <p className="mt-2 text-sm text-slate-600">Chưa có nguồn tham khảo nào được duyệt cho ngữ cảnh này.</p>}
      </section>
      {props.children}
      <section aria-label="Nguồn chờ duyệt / quản lý curation"><h2 className="text-lg font-semibold text-slate-900">Nguồn chờ duyệt / quản lý curation</h2>
        {!props.loading && matches && <p className="mt-2 text-sm text-slate-600">Chủ đề chưa có nguồn. Hãy thêm tài liệu vào kho nguồn trước khi bắt đầu duyệt.</p>}
      </section>
    </> : <CurationTopic key={`${user!.id}:${user!.role}:${factorTopicKey(props.diseaseGroupId, props.factor)}:${library.topic_id}`} selector={selector} library={library}>{props.children}</CurationTopic>}
  </section>;
}

function CurationTopic({ selector, library, children }: { selector: ReferenceSelector; library: TopicSourceLibrary; children?: ReactNode }) {
  const [states, setStates] = useState<ReferenceState[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  const listEpoch = useRef(0);
  const listController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; listEpoch.current++; listController.current?.abort(); mutationController.current?.abort(); };
  }, []);

  async function refresh(currentId?: number, expectedSourceId?: number) {
    const epoch = ++listEpoch.current;
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    setLoading(true); setListError(null); setStates(null);
    try {
      const [result, current] = await Promise.all([
        listParentReferenceCurations(selector, controller.signal),
        currentId === undefined ? Promise.resolve(null) : getParentReferenceCuration(currentId, selector, controller.signal),
      ]);
      if (!mounted.current || epoch !== listEpoch.current) return;
      if (result.topic_id !== library.topic_id || (current && (current.topic_id !== library.topic_id || current.source_id !== expectedSourceId))) throw new Error('Context mismatch');
      const items = result.items.map(item => current && current.approval_id === item.approval_id && current.version > item.version ? current : item);
      setStates(items);
    } catch (error) {
      if (mounted.current && epoch === listEpoch.current) setListError(parentReferenceError(error));
    } finally {
      if (mounted.current && epoch === listEpoch.current) setLoading(false);
    }
  }
  useEffect(() => { void refresh(); }, [library]); // Same-selector imports refresh metadata; topic/user changes remount this scope.

  async function mutate(sourceId: number, state: ReferenceState | undefined, operation: Operation, note: string, proofId?: number) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setNotice(null);
    const controller = new AbortController();
    mutationController.current = controller;
    try {
      const result = operation === 'create' ? await createParentReferenceDraft(selector, sourceId, note, controller.signal)
        : operation === 'approve' ? await approveParentReference(state!.approval_id, selector, state!.version, proofId!, note, controller.signal)
          : operation === 'revoke' ? await revokeParentReference(state!.approval_id, state!.version, note, controller.signal)
            : await reopenParentReference(state!.approval_id, state!.version, note, controller.signal);
      if (!mounted.current) return;
      setNotice({ error: false, text: operation === 'create' ? 'Đã bắt đầu xem xét nguồn cho phụ huynh.'
        : operation === 'approve' ? 'Đã duyệt liên kết tài liệu cho phụ huynh.'
          : operation === 'revoke' ? 'Đã thu hồi liên kết. Nguồn vẫn được giữ trong kho.' : 'Đã mở lại để duyệt. Hãy xem và chọn bằng chứng lại.' });
      await refresh(result.approval_id, sourceId);
    } catch (error) {
      if (!mounted.current) return;
      setNotice({ error: true, text: parentReferenceError(error) });
      // Never retry the mutation. Reload persisted state and remount cards to
      // clear proof selection, including conflicts that leave version unchanged.
      await refresh(state?.approval_id, sourceId);
    } finally {
      if (mounted.current) { busyRef.current = false; setBusy(false); }
    }
  }

  const approved = (states ?? []).filter(item => item.status === 'APPROVED' && item.source_in_library && item.evidence_content_id !== null && item.policy_decision === 'ALLOW_PARENT_REFERENCE');
  function renderSource(source: TopicSourceLibraryItem, compact = false) {
    const state = states?.find(item => item.source_id === source.source_id);
    return <SourceCuration key={`${source.source_id}:${state?.approval_id ?? 'new'}:${state?.version ?? 0}:${state?.status ?? 'none'}`} source={source} state={state} selector={selector} topicId={library.topic_id!} busy={busy} onMutate={mutate} compact={compact} />;
  }
  return <div className="space-y-6">
    <section aria-label="Nguồn đang hiển thị cho phụ huynh" className="space-y-3 border-b border-slate-200 pb-5">
      <h2 className="text-lg font-semibold text-slate-900">Nguồn đang hiển thị cho phụ huynh</h2>
      <p className="text-sm leading-6 text-slate-600">Nguồn đã duyệt có bằng chứng và chính sách hiện tại phù hợp. Parent tiếp tục xác minh khi đọc; tài liệu độc lập với kết quả và giải thích của mô hình.</p>
      {loading ? <p className="text-sm text-slate-600">Đang tải nguồn đã duyệt…</p> : listError ? <p className="text-sm text-slate-600">Chưa xác định được nguồn đã duyệt. Vui lòng tải lại trạng thái.</p>
        : approved.length === 0 ? <p className="text-sm text-slate-600">Chưa có nguồn tham khảo nào được duyệt cho ngữ cảnh này.</p>
          : library.sources.filter(source => approved.some(item => item.source_id === source.source_id)).map(source => renderSource(source, true))}
    </section>
    {children}
    <section aria-label="Nguồn chờ duyệt / quản lý curation" className="space-y-4">
    <h2 className="text-lg font-semibold text-slate-900">Nguồn chờ duyệt / quản lý curation</h2>
    <p className="text-sm leading-6 text-slate-600">Nguồn có trong kho chưa đồng nghĩa đã được duyệt cho phụ huynh. Chọn và kiểm tra bằng chứng trước khi duyệt liên kết.</p>
    <button type="button" className={buttonStyle} disabled={busy || loading} onClick={() => void refresh()}>Tải lại trạng thái duyệt</button>
    {notice && <p role={notice.error ? 'alert' : 'status'} className={`rounded-lg p-3 text-sm ${notice.error ? 'bg-red-50 text-red-800' : 'bg-slate-50 text-slate-900'}`}>{notice.text}</p>}
    {loading && <p role="status" className="text-sm text-slate-500">Đang tải trạng thái duyệt…</p>}
    {listError && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{listError}</p>}
    {states !== null && library.sources.filter(source => !approved.some(item => item.source_id === source.source_id)).map(source => renderSource(source))}
    </section>
  </div>;
}

function SourceCuration({ source, state, selector, topicId, busy, onMutate, compact = false }: {
  source: TopicSourceLibraryItem; state?: ReferenceState; selector: ReferenceSelector; topicId: number; busy: boolean;
  compact?: boolean;
  onMutate: (sourceId: number, state: ReferenceState | undefined, operation: Operation, note: string, proofId?: number) => Promise<void>;
}) {
  const [note, setNote] = useState('');
  const [proofOpen, setProofOpen] = useState(false);
  const [proofs, setProofs] = useState<ProofCandidate[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [proofLoading, setProofLoading] = useState(false);
  const [proofError, setProofError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [events, setEvents] = useState<ReferenceEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState(false);
  const mounted = useRef(false);
  const proofEpoch = useRef(0), historyEpoch = useRef(0);
  const proofController = useRef<AbortController | null>(null), historyController = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; proofEpoch.current++; historyEpoch.current++; proofController.current?.abort(); historyController.current?.abort(); };
  }, []);

  async function fetchProofs(offset: number) {
    const epoch = ++proofEpoch.current;
    proofController.current?.abort();
    const controller = new AbortController(); proofController.current = controller;
    setProofLoading(true); setProofError(null);
    try {
      const result = await getParentReferenceProofCandidates(selector, source.source_id, offset, controller.signal);
      if (!mounted.current || epoch !== proofEpoch.current) return;
      if (result.topic_id !== topicId) throw new Error('Topic mismatch');
      setProofs(previous => [...new Map((offset === 0 ? result.candidates : [...previous, ...result.candidates]).map(item => [item.evidence_content_id, item])).values()]);
      setNextOffset(result.next_offset);
    } catch (error) {
      if (mounted.current && epoch === proofEpoch.current) { setProofError(parentReferenceError(error)); setSelected(null); }
    } finally {
      if (mounted.current && epoch === proofEpoch.current) setProofLoading(false);
    }
  }
  function toggleProofs() {
    proofEpoch.current++; proofController.current?.abort();
    setSelected(null); setProofs([]); setNextOffset(null); setProofError(null); setProofLoading(false);
    setProofOpen(!proofOpen);
    if (!proofOpen) void fetchProofs(0);
  }
  async function fetchHistory() {
    if (!state) return;
    const epoch = ++historyEpoch.current;
    historyController.current?.abort();
    const controller = new AbortController(); historyController.current = controller;
    setHistoryLoading(true); setHistoryError(null);
    try {
      const result = await getParentReferenceHistory(state.approval_id, controller.signal);
      if (mounted.current && epoch === historyEpoch.current) setEvents(result);
    } catch (error) {
      if (mounted.current && epoch === historyEpoch.current) setHistoryError(parentReferenceError(error));
    } finally {
      if (mounted.current && epoch === historyEpoch.current) setHistoryLoading(false);
    }
  }
  function toggleHistory() {
    historyEpoch.current++; historyController.current?.abort();
    setHistoryOpen(!historyOpen); setEvents([]); setHistoryError(null); setHistoryLoading(false);
    if (!historyOpen) void fetchHistory();
  }
  const selectedProof = proofs.find(item => item.evidence_content_id === selected);
  const canApprove = state?.status === 'DRAFT' && state.source_in_library && selectedProof?.policy_decision === 'ALLOW_PARENT_REFERENCE' && !proofLoading && !proofError;
  const noteId = `parent-reference-note-${source.source_id}`;
  const noteField = <>
    <label htmlFor={noteId} className="mt-4 block text-sm text-slate-700">Ghi chú duyệt nguồn #{source.source_id} (không bắt buộc, tối đa 1000 ký tự)</label>
    <textarea id={noteId} value={note} maxLength={1000} disabled={busy} onChange={event => setNote(event.target.value.slice(0, 1000))} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm" rows={2} />
  </>;
  return <article aria-label={`Duyệt nguồn ${source.source_id}`} className="rounded-xl border border-slate-200 p-4">
    <h3 className="font-semibold text-slate-900 [overflow-wrap:anywhere]">Nguồn tham khảo: {source.title}</h3>
    <p className="mt-1 text-sm text-slate-600 [overflow-wrap:anywhere]">Trong kho nguồn của chủ đề · {source.provider_id ?? 'Nguồn đã lưu'}{source.journal ? ` · ${source.journal}` : ''}{source.publication_year ? ` · ${source.publication_year}` : ''}</p>
    <p className="mt-3 font-semibold text-slate-900">Phụ huynh: {state?.status === 'APPROVED' && !compact ? 'Đã duyệt, hiện chưa đủ điều kiện hiển thị' : state ? STATUS_LABEL[state.status] : 'Chưa duyệt cho phụ huynh'}</p>
    {!state && <p className="mt-2 text-sm text-slate-600">Điều kiện nguồn: Chưa đủ điều kiện — cần chọn bằng chứng và xác minh.</p>}
    {state && <div className="mt-2 space-y-1 text-xs text-slate-600">
      <p>Phiên bản duyệt: {state.version}</p>
      <p>Điều kiện nguồn hiện tại: {POLICY_LABEL[state.policy_decision]}</p>
      <details><summary className="cursor-pointer text-blue-700">Xem chi tiết xác minh nguồn</summary><p className="mt-2 [overflow-wrap:anywhere]">Nguồn #{source.source_id} · Bằng chứng #{state.evidence_content_id ?? '—'} · {state.policy_decision} · {state.policy_reason_code}</p></details>
      {!state.source_in_library && <p role="alert">Nguồn không còn thuộc kho của chủ đề. Không thể duyệt lại.</p>}
      {state.approved_at && <p>Duyệt lúc: <time dateTime={state.approved_at}>{state.approved_at}</time> · Tài khoản #{state.approved_by ?? '—'}</p>}
      {state.source.original_url && <a href={state.source.original_url} target="_blank" rel="noopener noreferrer" className="inline-block text-blue-700 underline">Xem nguồn<span className="sr-only">: {source.title} (mở tab mới)</span></a>}
    </div>}
    {compact ? <details className="mt-3"><summary className="cursor-pointer text-sm text-blue-700">Ghi chú duyệt</summary>{noteField}</details> : noteField}
    <div className="mt-3 flex flex-wrap gap-2">
      {!state && <button type="button" className={buttonStyle} disabled={busy} onClick={() => void onMutate(source.source_id, state, 'create', note)}>Bắt đầu duyệt cho phụ huynh</button>}
      {state?.status === 'DRAFT' && <button type="button" className={buttonStyle} disabled={busy} aria-expanded={proofOpen} onClick={toggleProofs}>{proofOpen ? 'Đóng phần bằng chứng' : 'Chọn bằng chứng xác minh'}</button>}
      {state?.status === 'APPROVED' && <button type="button" className={buttonStyle} disabled={busy} onClick={() => setRevokeConfirm(true)}>Thu hồi khỏi phụ huynh</button>}
      {state?.status === 'REVOKED' && <button type="button" className={buttonStyle} disabled={busy} onClick={() => void onMutate(source.source_id, state, 'reopen', note)}>Mở lại để duyệt</button>}
      {state && <button type="button" className={buttonStyle} disabled={busy} aria-expanded={historyOpen} onClick={toggleHistory}>{historyOpen ? 'Đóng lịch sử duyệt' : 'Lịch sử duyệt'}</button>}
    </div>
    {proofOpen && state?.status === 'DRAFT' && <div className="mt-4 space-y-3 rounded-lg bg-slate-50 p-3">
      <p className="text-sm text-slate-600">Chọn rõ một bằng chứng đã kiểm tra. Điều kiện do backend xác minh; duyệt sẽ kiểm tra lại dữ liệu hiện tại.</p>
      {proofs.map(item => <div key={item.evidence_content_id} className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm">
        <input type="radio" name={`parent-proof-${source.source_id}`} aria-label={`Chọn bằng chứng #${item.evidence_content_id}`} checked={selected === item.evidence_content_id} disabled={busy || proofLoading} onChange={() => setSelected(item.evidence_content_id)} className="mt-1" />
        <div className="min-w-0"><strong className="block">Bằng chứng #{item.evidence_content_id}</strong>
          <span className="mt-1 block font-semibold text-slate-800">{POLICY_LABEL[item.policy_decision]}</span>
          <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer text-blue-700">Xem chi tiết xác minh</summary>
            <span className="mt-2 block [overflow-wrap:anywhere]">evidence_content_id: {item.evidence_content_id} · source_id: {item.source_id}</span>
            <span className="block [overflow-wrap:anywhere]">content_kind: {item.content_kind} · content_origin: {item.content_origin}</span>
            <span className="block [overflow-wrap:anywhere]">external_identifier: {item.external_identifier ?? '—'}</span>
            <span className="block">retrieved_at: <time dateTime={item.retrieved_at}>{item.retrieved_at}</time></span>
            <span className="block [overflow-wrap:anywhere]">content_sha256: {item.content_sha256}</span>
            <span className="block [overflow-wrap:anywhere]">{item.policy_decision} · {item.policy_reason_code}</span>
          </details>
        </div>
      </div>)}
      {proofLoading && <p role="status" className="text-sm text-slate-500">Đang tải bằng chứng…</p>}
      {proofError && <div><p role="alert" className="text-sm text-red-700">{proofError}</p><button type="button" className={buttonStyle} disabled={busy || proofLoading} onClick={() => void fetchProofs(proofs.length === 0 ? 0 : nextOffset ?? 0)}>Tải lại bằng chứng</button></div>}
      {!proofLoading && !proofError && proofs.length === 0 && <p className="text-sm text-slate-600">Chưa có bằng chứng xác minh cho nguồn này. Không thể duyệt.</p>}
      {!proofLoading && !proofError && proofs.length > 0 && !proofs.some(item => item.policy_decision === 'ALLOW_PARENT_REFERENCE') && <p className="text-sm text-amber-800">Các bằng chứng đã tải chưa đủ điều kiện để duyệt.</p>}
      {nextOffset !== null && <button type="button" className={buttonStyle} disabled={busy || proofLoading} onClick={() => void fetchProofs(nextOffset)}>Tải thêm bằng chứng</button>}
      <button type="button" className={`${buttonStyle} border-blue-400 text-blue-800`} disabled={busy || !canApprove} onClick={() => void onMutate(source.source_id, state, 'approve', note, selected!)}>Duyệt và hiển thị cho phụ huynh</button>
    </div>}
    {revokeConfirm && <div role="dialog" aria-modal="true" aria-label="Xác nhận thu hồi nguồn" onKeyDown={event => { if (event.key === 'Escape' && !busy) setRevokeConfirm(false); }} className="mt-4 rounded-xl border border-rose-300 p-4">
      <p className="text-sm text-slate-800">Bạn xác nhận thu hồi liên kết này khỏi phần phụ huynh? Tài liệu vẫn được giữ trong kho nguồn.</p>
      <div className="mt-3 flex gap-2"><button type="button" className={buttonStyle} disabled={busy} onClick={() => setRevokeConfirm(false)} autoFocus>Hủy</button>
        <button type="button" className={buttonStyle} disabled={busy} onClick={() => void onMutate(source.source_id, state, 'revoke', note)}>Xác nhận thu hồi</button></div>
    </div>}
    {historyOpen && <div className="mt-4 rounded-lg bg-slate-50 p-3">
      <h4 className="font-semibold text-slate-800">Lịch sử duyệt nguồn #{source.source_id}</h4>
      {historyLoading && <p role="status" className="text-sm text-slate-500">Đang tải lịch sử…</p>}
      {historyError && <div><p role="alert" className="text-sm text-red-700">{historyError}</p><button type="button" className={buttonStyle} onClick={() => void fetchHistory()}>Tải lại lịch sử</button></div>}
      {!historyLoading && !historyError && events.length === 0 && <p className="text-sm text-slate-600">Chưa có lịch sử duyệt.</p>}
      <ol className="mt-2 space-y-2">{events.map(item => <li key={item.id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
        <p className="font-medium">{ACTION_LABEL[item.action]} · Phiên bản {item.resulting_version}</p>
        <p className="text-xs text-slate-600">{item.from_status ? STATUS_LABEL[item.from_status] : 'Chưa bắt đầu'} → {STATUS_LABEL[item.to_status]} · Tài khoản #{item.actor_user_id ?? '—'}</p>
        <time dateTime={item.created_at} className="text-xs text-slate-600">{item.created_at}</time>
        {item.review_note && <p className="mt-1 whitespace-pre-wrap break-words text-slate-700">{item.review_note}</p>}
      </li>)}</ol>
    </div>}
  </article>;
}
