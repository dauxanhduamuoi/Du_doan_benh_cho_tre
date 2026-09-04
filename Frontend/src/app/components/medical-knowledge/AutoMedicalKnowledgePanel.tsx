import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Bot, CheckCircle2, ChevronDown, Clock3, Eye, EyeOff,
  Filter, Loader2, RefreshCw, RotateCcw, Search, ShieldAlert,
} from 'lucide-react';
import {
  autoMedicalKnowledgeErrorMessage, getAutoMedicalKnowledgeOverview,
  regenerateAutoMedicalKnowledge, retryAutoMedicalKnowledgeJob,
  setAutoMedicalKnowledgeVisibility, updateAutoMedicalKnowledgeSettings,
  type AutoDiscoveryDiagnostics, type AutoMedicalKnowledgeJob,
  type AutoMedicalKnowledgeJobStatus, type AutoMedicalKnowledgeOverview,
  type AutoMedicalKnowledgeRevision,
} from '@/lib/medicalKnowledgeApi';

const STATUS_LABELS: Record<AutoMedicalKnowledgeJobStatus, string> = {
  QUEUED: 'Đang chờ', SEARCHING: 'Đang tìm nguồn', GENERATING: 'Đang tạo nội dung',
  READY: 'Hoàn thành', INSUFFICIENT: 'Không đủ bằng chứng', FAILED: 'Lỗi', CANCELLED: 'Đã hủy',
};
const STRUCTURAL_CODES = new Set([
  'AUTO_OUTPUT_JSON_INVALID', 'AUTO_OUTPUT_SCHEMA_INVALID', 'AUTO_OUTPUT_MISSING_REQUIRED_FIELD',
  'AUTO_OUTPUT_INVALID_ENUM', 'AUTO_OUTPUT_SOURCE_SET_MISMATCH', 'AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID',
  'AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED', 'AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY', 'AUTO_OUTPUT_PROVIDER_INCOMPLETE',
]);
const FAILURE_MESSAGES: Record<string, string> = {
  PUBMED_SEARCH_FAILED: 'PubMed hiện không phản hồi hoặc truy vấn tìm kiếm thất bại.',
  PMC_ENRICHMENT_FAILED: 'Không thể lấy nội dung PMC cho các nguồn đã tìm thấy.',
  LLM_PROVIDER_FAILED: 'Dịch vụ tạo nội dung hiện không khả dụng.',
  LLM_RATE_LIMITED: 'Dịch vụ AI đang giới hạn lượt gọi. Hệ thống sẽ tự tiếp tục sau thời gian chờ.',
  LLM_INVALID_RESPONSE: 'Lỗi lịch sử cũ — phiên bản này chưa lưu đủ chi tiết để phân loại chính xác.',
  AUTO_OUTPUT_JSON_INVALID: 'Kết quả AI không phải một JSON hợp lệ duy nhất.',
  AUTO_OUTPUT_SCHEMA_INVALID: 'Kết quả AI không đúng lược đồ dữ liệu bắt buộc.',
  AUTO_OUTPUT_MISSING_REQUIRED_FIELD: 'Kết quả AI thiếu trường dữ liệu bắt buộc.',
  AUTO_OUTPUT_INVALID_ENUM: 'Kết quả AI dùng giá trị phân loại không hợp lệ.',
  AUTO_OUTPUT_SOURCE_SET_MISMATCH: 'Kết quả AI không đánh giá đúng và đủ tập nguồn đã chọn.',
  AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID: 'Phản hồi của dịch vụ AI không chứa dữ liệu có cấu trúc có thể xử lý.',
  AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED: 'Dịch vụ AI đã từ chối yêu cầu tạo dữ liệu có cấu trúc.',
  AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY: 'Dịch vụ AI đã hoàn tất nhưng không trả về nội dung có cấu trúc.',
  AUTO_OUTPUT_PROVIDER_INCOMPLETE: 'Dịch vụ AI chưa hoàn tất nội dung có cấu trúc.',
  AUTO_OUTPUT_UNSUPPORTED_NUMBER: 'Nội dung AI có số liệu không tìm thấy trong bằng chứng đã chọn.',
  AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED: 'Nội dung AI sử dụng một số liệu nhưng không khai báo nguồn hỗ trợ.',
  AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID: 'Nguồn được khai báo cho số liệu không thuộc bộ bằng chứng đã chọn.',
  AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH: 'Không tìm thấy bằng chứng hỗ trợ số liệu trong nguồn đã khai báo.',
  AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID: 'Loại số liệu AI khai báo không phù hợp với nội dung.',
  AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH: 'Loại số liệu AI khai báo khác với ý nghĩa trong nguồn và phần giải thích.',
  AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE: 'Nội dung AI khai báo trùng nguồn hỗ trợ cho cùng một số liệu.',
  AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED: 'Nội dung AI khai báo một số liệu không được sử dụng trong phần giải thích.',
  AUTO_OUTPUT_CAUSAL_OVERCLAIM: 'Nội dung khẳng định quan hệ nhân quả vượt quá bằng chứng.',
  AUTO_OUTPUT_UNSUPPORTED_MECHANISM: 'Nội dung có một cơ chế không được nguồn hỗ trợ.',
  AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID: 'Khẳng định về trẻ em không có bằng chứng nhi khoa trực tiếp.',
  AUTO_OUTPUT_PERSONALIZED_LANGUAGE: 'Nội dung dùng ngôn ngữ cá nhân hóa hoặc chẩn đoán.',
  AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT: 'Mức bằng chứng không nhất quán với đánh giá các nguồn.',
  AUTO_OUTPUT_UNSUPPORTED_SOURCE_CLAIM: 'Khẳng định về nguồn không được bằng chứng hỗ trợ.',
  AUTO_OUTPUT_VALIDATION_FAILED: 'Nội dung tạo ra không vượt qua kiểm tra an toàn.',
  PERSISTENCE_FAILED: 'Không thể lưu kết quả xử lý.',
  DRAFTGENERATOROUTPUTERROR: 'Lịch sử cũ: dịch vụ trả dữ liệu không hợp lệ.',
  DRAFTGENERATORRATELIMITERROR: 'Dịch vụ AI đang giới hạn lượt gọi.',
  UNKNOWN_INTERNAL_ERROR: 'Quy trình gặp lỗi kỹ thuật chưa xác định.',
};
const INSUFFICIENT_MESSAGES: Record<string, string> = {
  NO_SEARCH_RESULTS: 'Các truy vấn đã chạy chưa trả về bài phù hợp.',
  NO_DISEASE_RELEVANT_SOURCE: 'Chưa tìm được bài đủ liên quan đến đúng nhóm bệnh.',
  NO_FACTOR_RELEVANT_SOURCE: 'Chưa tìm được bài đánh giá trực tiếp yếu tố đã chọn.',
  NO_PEDIATRIC_RELEVANT_SOURCE: 'Chưa tìm được bài có phạm vi trẻ em phù hợp.',
  NO_USABLE_EVIDENCE: 'Các bài phù hợp chưa có nội dung mà hệ thống có thể đọc.',
  NO_DIRECT_SUPPORT: 'Các nguồn được đánh giá chưa hỗ trợ trực tiếp cho chủ đề.',
  CONFLICTING_EVIDENCE: 'Các nguồn được chọn cho kết quả không nhất quán.',
};
const CALL_PURPOSE_LABELS: Record<string, string> = {
  INITIAL: 'Tạo nội dung ban đầu', STRUCTURAL_RETRY: 'Sửa cấu trúc đầu ra', CONTRACT_REPAIR: 'Sửa cấu trúc nội dung',
};
type StatusFilter = 'CURRENT' | 'FAILED' | 'INSUFFICIENT' | 'READY';
type GenerationFilter = 'ALL' | 'AI_FULL' | 'SAFE_FALLBACK' | 'INSUFFICIENT';

function Disclosure({ title, tone = 'neutral', children }: { title: string; tone?: 'neutral' | 'danger'; children: React.ReactNode }) {
  return <details className={`group mt-3 rounded-xl border p-3 text-xs ${tone === 'danger' ? 'border-red-200 bg-red-50 text-red-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
    <summary className="flex cursor-pointer list-none items-center justify-between font-semibold">{title}<ChevronDown size={14} className="transition group-open:rotate-180" /></summary>
    <div className="mt-3">{children}</div>
  </details>;
}

function DiscoveryDetails({ diagnostics }: { diagnostics: AutoDiscoveryDiagnostics | null }) {
  if (!diagnostics) return null;
  const counts = [
    ['Truy vấn đã chạy', diagnostics.queries_run], ['Kết quả PubMed', diagnostics.raw_results],
    ['Sau loại trùng', diagnostics.deduplicated], ['Liên quan đến bệnh', diagnostics.disease_relevant],
    ['Liên quan đến yếu tố', diagnostics.factor_relevant], ['Có phạm vi trẻ em', diagnostics.pediatric_relevant],
    ['AI có nội dung để đọc', diagnostics.usable_evidence], ['Nguồn dùng để tạo', diagnostics.selected_for_generation],
  ] as const;
  return <Disclosure title="Chi tiết tìm kiếm">
    <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">{counts.map(([label, value]) => <div key={label} className="flex justify-between gap-3"><dt>{label}</dt><dd className="font-semibold">{value}</dd></div>)}</dl>
    {diagnostics.queries.length ? <div className="mt-3"><p className="font-semibold">Truy vấn an toàn đã chạy</p><ol className="mt-1 list-decimal space-y-1 pl-5">{diagnostics.queries.map((value, index) => <li key={`${index}-${value}`} className="break-words font-mono">{value}</li>)}</ol></div> : null}
    {diagnostics.sources.length ? <div className="mt-3"><p className="font-semibold">Nguồn đã xét (không hiển thị nội dung bằng chứng)</p><ul className="mt-1 list-disc space-y-1 pl-5">{diagnostics.sources.map((source, index) => <li key={`${source.pmid}-${index}`}>{source.title} (PMID {source.pmid}) — {source.decision === 'SELECTED' ? 'đã chọn' : 'đã loại'}</li>)}</ul></div> : null}
  </Disclosure>;
}

function ValidationDetails({ job }: { job: AutoMedicalKnowledgeJob }) {
  const failure = job.diagnostics?.failure;
  if (!failure) return null;
  return <Disclosure title="Chi tiết kiểm tra" tone="danger">
    <p>Kết quả AI không vượt qua kiểm tra cấu trúc hoặc an toàn.</p>
    <p className="mt-1"><strong>Lý do:</strong> {FAILURE_MESSAGES[failure.code] ?? failure.safe_detail}</p>
    <p className="mt-1"><strong>Mã:</strong> <code>{failure.code}</code></p>
    {failure.field ? <p><strong>Trường:</strong> <code>{failure.field}</code></p> : null}
    {failure.source_id ? <p><strong>Nguồn:</strong> {failure.source_id}</p> : null}
    {failure.numeric_value ? <p><strong>Giá trị:</strong> {failure.numeric_value}</p> : null}
    {failure.call_purpose ? <p><strong>Giai đoạn:</strong> {CALL_PURPOSE_LABELS[failure.call_purpose] ?? failure.call_purpose}</p> : null}
    {failure.generation_call_number ? <p><strong>Lần gọi:</strong> {failure.generation_call_number}{failure.max_generation_calls ? ` / ${failure.max_generation_calls}` : ''}</p> : null}
    {failure.http_status ? <p><strong>HTTP:</strong> {failure.http_status}</p> : null}
    {failure.provider ? <p><strong>Provider:</strong> {failure.provider.toUpperCase()}</p> : null}
    {failure.provider_error_category ? <p><strong>Loại lỗi provider:</strong> <code>{failure.provider_error_category}</code></p> : null}
  </Disclosure>;
}

type TopicIdentity = Pick<AutoMedicalKnowledgeJob, 'disease_group_id' | 'factor_type' | 'factor_key' | 'factor_value'>;
const topicKey = (topic: TopicIdentity) => [topic.disease_group_id, topic.factor_type, topic.factor_key, topic.factor_value ?? ''].join('|');
const topicLabel = (topic: TopicIdentity) => `${topic.disease_group_id} · ${topic.factor_value ?? topic.factor_key}`;
export const AUTO_OVERVIEW_POLL_INTERVAL_MS = 3_000;
const ACTIVE_JOB_STATUSES = new Set<AutoMedicalKnowledgeJobStatus>(['QUEUED', 'SEARCHING', 'GENERATING']);

export default function AutoMedicalKnowledgePanel({ canManage }: { canManage: boolean }) {
  const [overview, setOverview] = useState<AutoMedicalKnowledgeOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('CURRENT');
  const [generationFilter, setGenerationFilter] = useState<GenerationFilter>('ALL');
  const [factorFilter, setFactorFilter] = useState('ALL');
  const [query, setQuery] = useState('');
  const [showLegacy, setShowLegacy] = useState(false);
  const [expandedRevisionIds, setExpandedRevisionIds] = useState<Set<number>>(new Set());
  const mountedRef = useRef(false);
  const backgroundRefreshInFlightRef = useRef(false);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const refresh = useCallback(async () => {
    try { setOverview(await getAutoMedicalKnowledgeOverview()); setError(null); }
    catch { setError('Không xác định được trạng thái dịch vụ Auto Medical Knowledge.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const backgroundRefresh = useCallback(async () => {
    if (backgroundRefreshInFlightRef.current) return;
    backgroundRefreshInFlightRef.current = true;
    try { const next = await getAutoMedicalKnowledgeOverview(); if (mountedRef.current) setOverview(next); }
    catch { /* Preserve the last confirmed UI state on a transient poll failure. */ }
    finally { backgroundRefreshInFlightRef.current = false; }
  }, []);
  const shouldPoll = Boolean(overview?.settings.enabled && overview.jobs.some((job) => job.is_current_attempt && ACTIVE_JOB_STATUSES.has(job.status)));
  useEffect(() => {
    if (!shouldPoll) return undefined;
    const id = window.setInterval(() => { void backgroundRefresh(); }, AUTO_OVERVIEW_POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [backgroundRefresh, shouldPoll]);
  useEffect(() => {
    const onFocus = () => { void backgroundRefresh(); };
    window.addEventListener('focus', onFocus); return () => window.removeEventListener('focus', onFocus);
  }, [backgroundRefresh]);

  async function run(key: string, action: () => Promise<unknown>) {
    setBusy(key); setError(null);
    try { await action(); await refresh(); } catch (reason) { setError(autoMedicalKnowledgeErrorMessage(reason)); } finally { setBusy(null); }
  }
  async function toggleRuntime() {
    if (!overview || !canManage) return;
    const enabled = !overview.settings.enabled;
    setBusy(enabled ? 'enabling-service' : 'disabling-service'); setError(null);
    try { await updateAutoMedicalKnowledgeSettings({ enabled }); await refresh(); }
    catch { setError('Không thể thay đổi trạng thái Auto Medical Knowledge.'); }
    finally { setBusy(null); }
  }

  const topicGroups = useMemo(() => {
    const groups = new Map<string, { current: AutoMedicalKnowledgeJob; history: AutoMedicalKnowledgeJob[] }>();
    for (const job of overview?.jobs ?? []) {
      const key = topicKey(job); const group = groups.get(key);
      if (!group) groups.set(key, { current: job, history: [] });
      else if (job.is_current_attempt) { group.history.push(group.current); group.current = job; }
      else group.history.push(job);
    }
    return [...groups.values()];
  }, [overview?.jobs]);
  const revisionsByTopic = useMemo(() => new Map((overview?.revisions ?? []).map((revision) => [topicKey(revision), revision])), [overview?.revisions]);
  const factorOptions = useMemo(() => {
    const topics: TopicIdentity[] = [...topicGroups.map(({ current }) => current), ...(overview?.revisions ?? [])];
    return [...new Map(topics.map((topic) => {
      const value = [topic.factor_type, topic.factor_key, topic.factor_value ?? ''].join('|');
      return [value, { value, label: `${topic.factor_type} · ${topic.factor_value ?? topic.factor_key}` }];
    })).values()];
  }, [overview?.revisions, topicGroups]);
  const normalizedQuery = query.trim().toLocaleLowerCase('vi');
  const commonMatch = (topic: TopicIdentity) => {
    const factorValue = [topic.factor_type, topic.factor_key, topic.factor_value ?? ''].join('|');
    return (factorFilter === 'ALL' || factorFilter === factorValue)
      && (!normalizedQuery || `${topic.disease_group_id} ${topic.factor_type} ${topic.factor_key} ${topic.factor_value ?? ''}`.toLocaleLowerCase('vi').includes(normalizedQuery));
  };
  const generationMatch = (revision?: AutoMedicalKnowledgeRevision, status?: AutoMedicalKnowledgeJobStatus) => {
    if (generationFilter === 'ALL') return true;
    if (generationFilter === 'INSUFFICIENT') return revision?.generation_status === 'INSUFFICIENT' || status === 'INSUFFICIENT';
    return revision?.generation_mode === generationFilter;
  };
  const grouped = topicGroups.filter(({ current }) => (statusFilter === 'CURRENT' || current.status === statusFilter) && commonMatch(current) && generationMatch(revisionsByTopic.get(topicKey(current)), current.status));
  const visibleRevisions = (overview?.revisions ?? []).filter((revision) => commonMatch(revision) && generationMatch(revision) && (statusFilter === 'CURRENT' || (statusFilter === 'READY' && revision.generation_status === 'READY') || (statusFilter === 'INSUFFICIENT' && revision.generation_status === 'INSUFFICIENT')));
  const counts = useMemo(() => {
    const jobs = topicGroups.map(({ current }) => current);
    return {
      active: jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).length,
      ready: jobs.filter((job) => job.status === 'READY').length,
      insufficient: jobs.filter((job) => job.status === 'INSUFFICIENT').length,
      failed: jobs.filter((job) => job.status === 'FAILED').length,
    };
  }, [topicGroups]);
  const cooldownActive = Boolean(overview?.provider_cooldown?.active && new Date(overview.provider_cooldown.cooldown_until).getTime() > Date.now());

  function JobContent({ job, historical = false }: { job: AutoMedicalKnowledgeJob; historical?: boolean }) {
    const semantic = Boolean(job.last_error_code?.startsWith('AUTO_OUTPUT_') && !STRUCTURAL_CODES.has(job.last_error_code));
    return <div className={historical ? 'mt-3 border-t border-slate-200 pt-3' : ''}>
      <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-slate-900">{topicLabel(job)}</strong><span className={`rounded-full px-2.5 py-1 text-xs font-bold ${job.status === 'FAILED' ? 'bg-red-100 text-red-800' : job.status === 'READY' ? 'bg-emerald-100 text-emerald-800' : job.status === 'INSUFFICIENT' ? 'bg-amber-100 text-amber-900' : 'bg-blue-100 text-blue-800'}`}>{historical ? 'Lịch sử — ' : ''}{STATUS_LABELS[job.status]}</span></div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>{job.factor_type} · attempt {job.attempt_count}</span>{canManage && job.status === 'FAILED' && !historical ? <button type="button" disabled={!overview?.settings.enabled || cooldownActive || busy !== null} onClick={() => void run(`retry-${job.id}`, () => retryAutoMedicalKnowledgeJob(job.id))} className="inline-flex items-center gap-1.5 rounded-lg bg-amber-700 px-3 py-1.5 font-semibold text-white disabled:opacity-50"><RotateCcw size={13} />{semantic ? 'Tạo lại' : 'Thử lại'}</button> : null}</div>
      {job.legacy ? <p className="mt-2 text-xs text-slate-500">Lịch sử cũ — dữ liệu chẩn đoán chi tiết chưa được ghi ở phiên bản này.</p> : null}
      {job.status === 'FAILED' ? <><p className="mt-2 text-sm text-red-700">{FAILURE_MESSAGES[job.last_error_code ?? ''] ?? 'Quy trình gặp lỗi kỹ thuật chưa xác định.'}</p>{job.last_error_code === 'LLM_RATE_LIMITED' && (overview?.provider_cooldown?.cooldown_until || job.next_retry_at) ? <p className="mt-1 text-xs text-slate-600">Tiếp tục sau: {new Date(overview?.provider_cooldown?.cooldown_until ?? job.next_retry_at ?? '').toLocaleString('vi-VN')}.</p> : null}{cooldownActive && !historical ? <p className="mt-1 text-xs text-amber-800">Nút thử lại tạm khóa trong thời gian dịch vụ AI chờ hạn mức.</p> : null}<ValidationDetails job={job} /></> : null}
      {job.status === 'INSUFFICIENT' ? <p className="mt-2 text-sm text-slate-600">{INSUFFICIENT_MESSAGES[job.diagnostics?.insufficient_reason ?? ''] ?? 'Hệ thống chưa tìm được bằng chứng phù hợp.'}</p> : null}
      {!historical ? <DiscoveryDetails diagnostics={job.diagnostics} /> : null}
    </div>;
  }
  const attempts = (job: AutoMedicalKnowledgeJob) => job.history.filter((attempt) => showLegacy || !attempt.legacy).map((attempt) => <div key={`${attempt.attempt}-${attempt.created_at}`} className="mt-2 border-t border-slate-200 pt-2 text-xs text-slate-600"><p className="font-semibold">Attempt {attempt.attempt} — {attempt.status === 'FAILED' ? 'Lỗi' : 'Lịch sử cũ'}</p>{attempt.failure_code ? <p>{FAILURE_MESSAGES[attempt.failure_code] ?? attempt.failure_code}</p> : null}{attempt.legacy ? <p>Lịch sử cũ — dữ liệu chẩn đoán chi tiết chưa được ghi ở phiên bản này.</p> : null}</div>);

  return <section aria-labelledby="auto-medical-heading" className="space-y-5">
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-start gap-3"><span className="rounded-xl bg-amber-100 p-2 text-amber-800"><ShieldAlert size={20} /></span><div><h2 id="auto-medical-heading" className="text-lg font-bold text-slate-950">Auto Medical Knowledge</h2><p className="mt-1 max-w-3xl text-sm leading-6 text-amber-950">Nội dung tự động chưa được kiểm duyệt y khoa. Cho phép hiển thị không phải là phê duyệt y khoa.</p></div></div><button type="button" onClick={() => void refresh()} disabled={loading || busy !== null} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 disabled:opacity-50"><RefreshCw size={15} /> Làm mới</button></div></div>
    {loading ? <p role="status" className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600"><Loader2 size={16} className="animate-spin" /> Đang tải hàng đợi Auto…</p> : null}
    {error ? <p role="alert" className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertTriangle size={16} /> {error}</p> : null}
    {overview ? <>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.7fr)]">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-bold text-slate-950">Điều khiển runtime</h3><p className="mt-1 text-sm text-slate-600">Dịch vụ: <strong>{overview.settings.enabled ? 'Đang bật' : 'Đang tắt'}</strong></p></div>{canManage ? <button type="button" role="switch" aria-label="Bật hoặc tắt Auto Medical Knowledge" aria-checked={overview.settings.enabled} disabled={busy !== null} onClick={() => void toggleRuntime()} className={`inline-flex min-w-28 items-center justify-center rounded-full px-4 py-2 text-sm font-bold text-white disabled:opacity-50 ${overview.settings.enabled ? 'bg-emerald-700' : 'bg-slate-600'}`}>{busy === 'enabling-service' ? 'Đang bật…' : busy === 'disabling-service' ? 'Đang tắt…' : overview.settings.enabled ? 'Tắt Auto' : 'Bật Auto'}</button> : null}</div><p className="mt-3 text-sm text-slate-500">{overview.settings.enabled ? 'Auto đang hoạt động.' : 'Auto đang tắt. Nội dung và lịch sử đã có vẫn được giữ nguyên.'}</p>{cooldownActive && overview.provider_cooldown ? <p role="status" className="mt-3 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">{overview.provider_cooldown.provider} đang tạm nghỉ do giới hạn lượt gọi. Tiếp tục sau: {new Date(overview.provider_cooldown.cooldown_until).toLocaleString('vi-VN')}.</p> : null}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"><label className="text-sm font-bold text-slate-900">Chế độ Parent<select aria-label="Chế độ hiển thị Auto cho Parent" value={overview.settings.display_mode} disabled={!canManage || busy !== null} onChange={(event) => void run('settings', () => updateAutoMedicalKnowledgeSettings({ display_mode: event.target.value as typeof overview.settings.display_mode }))} className="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-normal"><option value="REVIEWED_ONLY">Chỉ nội dung đã kiểm duyệt</option><option value="REVIEWED_WITH_AUTO_FALLBACK">Kiểm duyệt trước, Auto dự phòng</option></select></label><p className="mt-2 text-xs leading-5 text-slate-500">Nội dung đã kiểm duyệt luôn giữ thứ tự ưu tiên hiện có.</p></section>
      </div>
      <section><h3 className="mb-3 font-bold text-slate-950">Tổng quan hàng đợi</h3><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
        ['Đang xử lý', counts.active, Clock3, 'bg-blue-50 text-blue-700'], ['Hoàn thành', counts.ready, CheckCircle2, 'bg-emerald-50 text-emerald-700'], ['Chưa đủ bằng chứng', counts.insufficient, Search, 'bg-amber-50 text-amber-800'], ['Lỗi', counts.failed, AlertTriangle, 'bg-red-50 text-red-700'],
      ].map(([label, count, Icon, color]) => { const ItemIcon = Icon as typeof Clock3; return <article key={label as string} className={`rounded-2xl border border-slate-200 p-4 ${color}`}><div className="flex items-center justify-between"><ItemIcon size={19} /><strong className="text-2xl text-slate-950">{count as number}</strong></div><p className="mt-3 text-sm font-semibold text-slate-700">{label as string}</p></article>; })}</div></section>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2"><Filter size={17} /><h3 className="font-bold">Tìm và lọc chủ đề</h3></div><div className="mt-3 grid gap-3 md:grid-cols-3"><label className="relative"><span className="sr-only">Tìm chủ đề Auto</span><Search size={15} className="absolute left-3 top-3 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Tìm chủ đề Auto" placeholder="Nhóm bệnh hoặc yếu tố…" className="w-full rounded-xl border border-slate-300 py-2.5 pl-9 pr-3 text-sm" /></label><select aria-label="Lọc chế độ tạo" value={generationFilter} onChange={(event) => setGenerationFilter(event.target.value as GenerationFilter)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi chế độ tạo</option><option value="AI_FULL">AI đầy đủ</option><option value="SAFE_FALLBACK">Bản rút gọn an toàn</option><option value="INSUFFICIENT">Không đủ bằng chứng</option></select><select aria-label="Lọc yếu tố Auto" value={factorFilter} onChange={(event) => setFactorFilter(event.target.value)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi yếu tố</option>{factorOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap gap-1" role="group" aria-label="Lọc trạng thái">{([['CURRENT', 'Hiện tại'], ['FAILED', 'Lỗi'], ['INSUFFICIENT', 'Chưa đủ bằng chứng'], ['READY', 'Hoàn thành']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={statusFilter === value} onClick={() => setStatusFilter(value)} className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${statusFilter === value ? 'bg-slate-800 text-white' : 'bg-white text-slate-700'}`}>{label}</button>)}</div><label className="inline-flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={showLegacy} onChange={(event) => setShowLegacy(event.target.checked)} /> Hiện lịch sử cũ</label></div></section>
      <div className="grid gap-5 xl:grid-cols-2 xl:items-start">
        <section className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5"><div className="flex justify-between"><div><h3 className="font-bold text-slate-950">Trạng thái hiện tại theo chủ đề</h3><p className="mt-1 text-xs text-slate-500">{grouped.length} chủ đề phù hợp</p></div><Clock3 size={18} /></div>{grouped.length === 0 ? <p className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">Không có kết quả phù hợp bộ lọc.</p> : <ul className="mt-4 space-y-3">{grouped.map(({ current, history }) => { const historyCount = history.length + current.history.length; return <li key={topicKey(current)} className="rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm"><JobContent job={current} />{historyCount ? <details className="group mt-3 rounded-lg border border-slate-200 px-3 py-2"><summary className="flex cursor-pointer list-none justify-between text-xs font-semibold">Lịch sử {historyCount} lần<ChevronDown size={14} className="transition group-open:rotate-180" /></summary>{attempts(current)}{history.filter((job) => showLegacy || !job.legacy).map((job) => <div key={job.id}><JobContent job={job} historical />{attempts(job)}</div>)}</details> : null}</li>; })}</ul>}</section>
        <section className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5">
          <div className="flex justify-between"><div><h3 className="font-bold text-slate-950">Nội dung Auto hiện tại</h3><p className="mt-1 text-xs text-slate-500">{visibleRevisions.length} revision phù hợp</p></div><Bot size={18} /></div>
          {visibleRevisions.length === 0 ? (
            <p className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">Chưa có nội dung Auto phù hợp bộ lọc.</p>
          ) : (
            <ul className="mt-4 space-y-3">{visibleRevisions.map((revision) => {
              const expanded = expandedRevisionIds.has(revision.id);
              return <li key={revision.id} className="rounded-xl border border-slate-200 bg-white shadow-sm">
                <button type="button" aria-expanded={expanded} aria-controls={`auto-revision-${revision.id}`} onClick={() => setExpandedRevisionIds((current) => { const next = new Set(current); if (next.has(revision.id)) next.delete(revision.id); else next.add(revision.id); return next; })} className="w-full cursor-pointer p-4 text-left">
                  <div className="flex items-start justify-between gap-3"><div className="min-w-0"><strong className="block truncate text-sm">{revision.disease_group_id} · {revision.factor_type} · {revision.factor_value ?? revision.factor_key}</strong><div className="mt-2 flex flex-wrap gap-1.5"><span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-bold text-emerald-800">{revision.generation_status === 'READY' ? 'Hoàn thành' : 'Chưa đủ bằng chứng'}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px]">{revision.is_visible ? 'Được phép hiển thị' : 'Đang ẩn'}</span></div><p className="mt-2 text-xs font-semibold text-slate-700">Chế độ tạo: {revision.generation_status === 'INSUFFICIENT' ? 'Không áp dụng' : revision.generation_mode === 'SAFE_FALLBACK' ? 'Bản rút gọn an toàn' : 'AI đầy đủ'}</p>{revision.generation_mode === 'SAFE_FALLBACK' ? <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-900">Bản AI đầy đủ không vượt qua kiểm tra hợp đồng đầu ra. Hệ thống đã dùng bản giải thích rút gọn từ bằng chứng đủ điều kiện.</p> : null}{revision.short_explanation_vi ? <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">{revision.short_explanation_vi}</p> : null}{revision.sources.length ? <p className="mt-2 truncate text-xs text-slate-500">{revision.sources.map((source) => `${source.title}${source.pmid ? ` (PMID ${source.pmid})` : ''}`).join(' · ')}</p> : null}</div><ChevronDown size={17} className={`shrink-0 transition ${expanded ? 'rotate-180' : ''}`} /></div>
                </button>
                <div id={`auto-revision-${revision.id}`} className={`overflow-hidden border-slate-200 px-4 text-sm transition-all ${expanded ? 'max-h-[64rem] border-t pb-4 pt-3 opacity-100' : 'max-h-0 opacity-0'}`}>
                  {revision.detailed_explanation_vi ? <p className="leading-6 text-slate-700">{revision.detailed_explanation_vi}</p> : null}
                  <p className="mt-3 text-xs text-slate-600">Mức bằng chứng: {revision.evidence_level} · {revision.sources.length} nguồn · revision {revision.revision_number}</p>
                  <Disclosure title={`Thông tin nguồn (${revision.sources.length})`}><p>Các nguồn tham chiếu đã được tóm tắt ngay trên card. Mở chi tiết tìm kiếm để xem provenance của pipeline.</p></Disclosure>
                  <DiscoveryDetails diagnostics={revision.diagnostics} />
                  {canManage ? <div className="mt-4 flex flex-wrap gap-2">{revision.generation_status === 'READY' ? <button type="button" disabled={busy !== null} onClick={() => void run(`visibility-${revision.id}`, () => setAutoMedicalKnowledgeVisibility(revision.id, !revision.is_visible))} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500 px-3 py-2 text-xs font-semibold text-amber-950 disabled:opacity-50">{revision.is_visible ? <EyeOff size={14} /> : <Eye size={14} />}{revision.is_visible ? 'Ẩn khỏi phụ huynh' : 'Cho phép hiển thị'}</button> : null}<button type="button" disabled={!overview.settings.enabled || busy !== null} onClick={() => void run(`regenerate-${revision.id}`, () => regenerateAutoMedicalKnowledge(revision.disease_group_id, revision))} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><RotateCcw size={14} /> Tạo lại</button></div> : null}
                </div>
              </li>;
            })}</ul>
          )}
        </section>
      </div>
    </> : null}
  </section>;
}
