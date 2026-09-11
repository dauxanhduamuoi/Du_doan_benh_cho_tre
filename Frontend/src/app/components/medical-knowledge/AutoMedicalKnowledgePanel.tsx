import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Baby, Bot, CalendarDays, CheckCircle2, ChevronDown, Clock3,
  CloudRain, CloudSun, Droplets, Eye, EyeOff, Filter, Loader2, RefreshCw,
  RotateCcw, Search, ShieldAlert, Thermometer, VenusAndMars, Wind,
} from 'lucide-react';
import {
  autoMedicalKnowledgeErrorMessage, getAutoMedicalKnowledgeOverview,
  regenerateAutoMedicalKnowledge, setAutoMedicalKnowledgeTopicVisibility,
  updateAutoMedicalKnowledgeSettings, type AutoDiscoveryDiagnostics,
  type AutoMedicalKnowledgeJob, type AutoMedicalKnowledgeJobStatus,
  type AutoMedicalKnowledgeOverview, type AutoMedicalKnowledgeRevision,
} from '@/lib/medicalKnowledgeApi';
import {
  AUTO_STATUS_PRESENTATIONS, AUTO_STATUS_TONE_CLASSES,
  getAutoTierPresentation, normalizeAutoSearch,
} from '@/lib/autoMedicalKnowledgePresentation';
import {
  FACTOR_FILTER_LABELS, getFactorPresentation, type MedicalFactorIconName,
  type MedicalFactorSelector, type MedicalFactorType,
} from '@/lib/medicalKnowledgeFactors';

export const AUTO_OVERVIEW_POLL_INTERVAL_MS = 3_000;
const ACTIVE_STATUSES = new Set<AutoMedicalKnowledgeJobStatus>(['QUEUED', 'SEARCHING', 'GENERATING']);
const FAILURE_MESSAGES: Record<string, string> = {
  PUBMED_SEARCH_FAILED: 'PubMed chưa phản hồi hoặc truy vấn tìm kiếm chưa hoàn thành.',
  PMC_ENRICHMENT_FAILED: 'Chưa thể lấy nội dung toàn văn cho các nguồn đã tìm thấy.',
  LLM_PROVIDER_FAILED: 'Dịch vụ tạo nội dung hiện không khả dụng.',
  LLM_RATE_LIMITED: 'Dịch vụ AI đang giới hạn lượt gọi. Hệ thống sẽ tiếp tục sau thời gian chờ.',
  AUTO_OUTPUT_VALIDATION_FAILED: 'Nội dung tạo ra chưa vượt qua kiểm tra an toàn.',
  PERSISTENCE_FAILED: 'Không thể lưu kết quả xử lý.',
};
const INSUFFICIENT_MESSAGES: Record<string, string> = {
  NO_SEARCH_RESULTS: 'Các truy vấn đã chạy chưa trả về tài liệu phù hợp.',
  NO_DISEASE_RELEVANT_SOURCE: 'Chưa tìm được tài liệu đủ liên quan đến đúng nhóm bệnh.',
  NO_FACTOR_RELEVANT_SOURCE: 'Chưa tìm được tài liệu đánh giá trực tiếp yếu tố đã chọn.',
  NO_PEDIATRIC_RELEVANT_SOURCE: 'Chưa tìm được tài liệu có phạm vi trẻ em phù hợp.',
  NO_USABLE_EVIDENCE: 'Các tài liệu phù hợp chưa có nội dung mà hệ thống có thể sử dụng.',
  NO_DIRECT_SUPPORT: 'Các nguồn được đánh giá chưa hỗ trợ trực tiếp cho chủ đề.',
  CONFLICTING_EVIDENCE: 'Các nguồn được chọn cho kết quả chưa nhất quán.',
};

type TopicIdentity = MedicalFactorSelector & { disease_group_id: string; disease_group_name: string };
type StatusFilter = 'ALL' | AutoMedicalKnowledgeJobStatus;
type TierFilter = 'ALL' | 'STRICT' | 'BASIC' | 'INSUFFICIENT';
type FactorFilter = 'ALL' | MedicalFactorType;
type VisibilityFilter = 'ALL' | 'VISIBLE' | 'HIDDEN' | 'INELIGIBLE';
interface JobTopic { current: AutoMedicalKnowledgeJob; previous: AutoMedicalKnowledgeJob[] }
interface DiseaseGroup<T> { id: string; name: string; items: T[] }

function topicKey(topic: Pick<TopicIdentity, 'disease_group_id' | 'factor_type' | 'factor_key' | 'factor_value'>) {
  return [topic.disease_group_id, topic.factor_type, topic.factor_key, topic.factor_value ?? ''].join('|');
}

function groupByDisease<T extends TopicIdentity>(items: T[]): DiseaseGroup<T>[] {
  const groups = new Map<string, DiseaseGroup<T>>();
  for (const item of items) {
    const group = groups.get(item.disease_group_id);
    if (group) group.items.push(item);
    else groups.set(item.disease_group_id, { id: item.disease_group_id, name: item.disease_group_name, items: [item] });
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name, 'vi'));
}

function FactorIcon({ name }: { name: MedicalFactorIconName }) {
  const props = { size: 17, 'aria-hidden': true } as const;
  if (name === 'temperature') return <Thermometer {...props} />;
  if (name === 'humidity') return <Droplets {...props} />;
  if (name === 'rain') return <CloudRain {...props} />;
  if (name === 'wind') return <Wind {...props} />;
  if (name === 'age') return <Baby {...props} />;
  if (name === 'sex') return <VenusAndMars {...props} />;
  if (name === 'seasonality') return <CalendarDays {...props} />;
  return <CloudSun {...props} />;
}

function FactorHeading({ topic }: { topic: TopicIdentity }) {
  const factor = getFactorPresentation(topic);
  return <div className="flex min-w-0 items-start gap-2.5">
    <span className="mt-0.5 rounded-lg bg-slate-100 p-2 text-slate-600"><FactorIcon name={factor.iconName} /></span>
    <div className="min-w-0"><strong className="block text-sm text-slate-950">{factor.title}</strong><span className="mt-0.5 block text-xs text-slate-500">{factor.categoryLabel}</span></div>
  </div>;
}

function StatusBadge({ status }: { status: AutoMedicalKnowledgeJobStatus }) {
  const item = AUTO_STATUS_PRESENTATIONS[status];
  return <span className={`inline-flex shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold ${AUTO_STATUS_TONE_CLASSES[item.tone]}`}>{item.label}</span>;
}

function Disclosure({ title, danger = false, children }: { title: string; danger?: boolean; children: React.ReactNode }) {
  return <details className={`group mt-3 rounded-xl border p-3 text-xs ${danger ? 'border-red-200 bg-red-50 text-red-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
    <summary className="flex cursor-pointer list-none items-center justify-between gap-2 font-semibold">{title}<ChevronDown size={14} className="shrink-0 transition group-open:rotate-180" /></summary>
    <div className="mt-3 space-y-1.5">{children}</div>
  </details>;
}

function DiscoveryDetails({ diagnostics }: { diagnostics: AutoDiscoveryDiagnostics | null }) {
  if (!diagnostics) return null;
  return <Disclosure title="Chi tiết tìm kiếm và sàng lọc">
    <p>Truy vấn: {diagnostics.queries_run} · Kết quả: {diagnostics.raw_results} · Sau khử trùng: {diagnostics.deduplicated}</p>
    <p>Đúng bệnh: {diagnostics.disease_relevant} · Đúng yếu tố: {diagnostics.factor_relevant} · Nhi khoa: {diagnostics.pediatric_relevant}</p>
    <p>Dùng được: {diagnostics.usable_evidence} · Chọn để tạo: {diagnostics.selected_for_generation}</p>
    {diagnostics.queries.length ? <p className="break-words">Cụm tìm kiếm: {diagnostics.queries.join(' · ')}</p> : null}
    {diagnostics.pipeline_version ? <p>Pipeline: {diagnostics.pipeline_version}</p> : null}
  </Disclosure>;
}

function ValidationDetails({ job }: { job: AutoMedicalKnowledgeJob }) {
  const failure = job.diagnostics?.failure;
  if (!failure && !job.last_error_code) return null;
  return <Disclosure title="Thông tin kỹ thuật" danger>
    <p>Mã lỗi: {failure?.code ?? job.last_error_code}</p>
    {failure?.safe_detail ? <p className="break-words">{failure.safe_detail}</p> : null}
    {failure?.provider_stage ? <p>Giai đoạn: {failure.provider_stage}</p> : null}
    {failure?.generation_calls != null ? <p>Lượt tạo: {failure.generation_calls}/{failure.max_generation_calls ?? '?'}</p> : null}
  </Disclosure>;
}

function DiseaseSection({ group, defaultOpen, statusSummary, children }: { group: Pick<DiseaseGroup<TopicIdentity>, 'id' | 'name' | 'items'>; defaultOpen: boolean; statusSummary: string; children: React.ReactNode }) {
  return <details open={defaultOpen} className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 sm:p-5">
      <div className="min-w-0"><h4 className="truncate font-bold text-slate-950">{group.name}</h4><p className="mt-1 text-xs text-slate-500">Mã nhóm #{group.id} · {group.items.length} chủ đề</p><p className="mt-1 text-xs font-medium text-slate-600">{statusSummary}</p></div>
      <ChevronDown size={18} className="shrink-0 text-slate-500 transition group-open:rotate-180" />
    </summary>
    <div className="border-t border-slate-200 p-3 sm:p-4">{children}</div>
  </details>;
}

function EmptyState({ onReset, children }: { onReset: () => void; children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-9 text-center text-sm text-slate-500"><p>{children}</p><button type="button" onClick={onReset} className="mt-3 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">Xóa bộ lọc</button></div>;
}

export default function AutoMedicalKnowledgePanel({ canManage, canManageVisibility = canManage }: { canManage: boolean; canManageVisibility?: boolean }) {
  const [overview, setOverview] = useState<AutoMedicalKnowledgeOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [tierFilter, setTierFilter] = useState<TierFilter>('ALL');
  const [factorFilter, setFactorFilter] = useState<FactorFilter>('ALL');
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>('ALL');
  const [query, setQuery] = useState('');
  const [showLegacy, setShowLegacy] = useState(false);
  const mountedRef = useRef(false);
  const pollingRef = useRef(false);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const refresh = useCallback(async () => {
    try { setOverview(await getAutoMedicalKnowledgeOverview()); setError(null); }
    catch { setError('Không xác định được trạng thái dịch vụ Auto Medical Knowledge.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const backgroundRefresh = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    try { const next = await getAutoMedicalKnowledgeOverview(); if (mountedRef.current) setOverview(next); }
    catch { /* Preserve the last confirmed state after a transient poll failure. */ }
    finally { pollingRef.current = false; }
  }, []);
  const shouldPoll = Boolean(overview?.settings.enabled && overview.jobs.some((job) => job.is_current_attempt && ACTIVE_STATUSES.has(job.status)));
  useEffect(() => {
    if (!shouldPoll) return undefined;
    const id = window.setInterval(() => { void backgroundRefresh(); }, AUTO_OVERVIEW_POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [backgroundRefresh, shouldPoll]);
  useEffect(() => { const onFocus = () => { void backgroundRefresh(); }; window.addEventListener('focus', onFocus); return () => window.removeEventListener('focus', onFocus); }, [backgroundRefresh]);

  async function run(key: string, action: () => Promise<unknown>, successMessage?: string) {
    setBusy(key); setError(null); setNotice(null);
    try { await action(); if (successMessage) setNotice(successMessage); await refresh(); }
    catch (reason) { setError(autoMedicalKnowledgeErrorMessage(reason)); }
    finally { setBusy(null); }
  }
  async function toggleRuntime() {
    if (!overview || !canManage) return;
    setBusy('runtime'); setError(null);
    try { await updateAutoMedicalKnowledgeSettings({ enabled: !overview.settings.enabled }); await refresh(); }
    catch { setError('Không thể thay đổi trạng thái Auto Medical Knowledge.'); }
    finally { setBusy(null); }
  }
  async function regenerate(topic: TopicIdentity) {
    setBusy(`regenerate-${topicKey(topic)}`); setError(null); setNotice(null);
    try { const result = await regenerateAutoMedicalKnowledge(topic.disease_group_id, topic); setNotice(result.created ? 'Đã tạo yêu cầu mới.' : result.message); await refresh(); }
    catch (reason) { setError(autoMedicalKnowledgeErrorMessage(reason)); }
    finally { setBusy(null); }
  }

  const jobTopics = useMemo(() => {
    const groups = new Map<string, JobTopic>();
    for (const job of overview?.jobs ?? []) {
      const key = topicKey(job); const group = groups.get(key);
      if (!group) groups.set(key, { current: job, previous: [] });
      else if (job.is_current_attempt) { group.previous.push(group.current); group.current = job; }
      else group.previous.push(job);
    }
    return [...groups.values()];
  }, [overview?.jobs]);
  const revisionsByTopic = useMemo(() => new Map((overview?.revisions ?? []).map((revision) => [topicKey(revision), revision])), [overview?.revisions]);
  const normalizedQuery = normalizeAutoSearch(query);
  const matchesTopic = useCallback((topic: TopicIdentity) => {
    if (factorFilter !== 'ALL' && topic.factor_type !== factorFilter) return false;
    if (!normalizedQuery) return true;
    const factor = getFactorPresentation(topic);
    return normalizeAutoSearch([topic.disease_group_name, topic.disease_group_id, ...factor.searchTerms].join(' ')).includes(normalizedQuery);
  }, [factorFilter, normalizedQuery]);
  const matchesTier = useCallback((revision?: AutoMedicalKnowledgeRevision, status?: AutoMedicalKnowledgeJobStatus) => {
    if (tierFilter === 'ALL') return true;
    if (tierFilter === 'INSUFFICIENT') return revision?.generation_status === 'INSUFFICIENT' || status === 'INSUFFICIENT';
    if (!revision || revision.generation_status !== 'READY') return false;
    return (revision.auto_tier ?? (revision.generation_mode === 'SAFE_FALLBACK' ? 'BASIC' : 'STRICT')) === tierFilter;
  }, [tierFilter]);
  const matchesVisibility = useCallback((revision?: AutoMedicalKnowledgeRevision) => {
    if (visibilityFilter === 'ALL') return true;
    if (!revision) return false;
    if (visibilityFilter === 'HIDDEN') return revision.topic_hidden_by_staff;
    if (visibilityFilter === 'VISIBLE') return !revision.topic_hidden_by_staff && revision.auto_display_eligible;
    return !revision.topic_hidden_by_staff && !revision.auto_display_eligible;
  }, [visibilityFilter]);
  const visibleJobs = jobTopics.filter(({ current }) => {
    const revision = revisionsByTopic.get(topicKey(current));
    return (statusFilter === 'ALL' || current.status === statusFilter) && matchesTopic(current) && matchesTier(revision, current.status) && matchesVisibility(revision);
  });
  const visibleRevisions = (overview?.revisions ?? []).filter((revision) => (
    (statusFilter === 'ALL' || (statusFilter === 'READY' && revision.generation_status === 'READY') || (statusFilter === 'INSUFFICIENT' && revision.generation_status === 'INSUFFICIENT'))
    && matchesTopic(revision) && matchesTier(revision) && matchesVisibility(revision)
  ));
  const jobDiseaseGroups = groupByDisease(visibleJobs.map(({ current }) => current));
  const revisionDiseaseGroups = groupByDisease(visibleRevisions);
  const jobsByKey = new Map(visibleJobs.map((group) => [topicKey(group.current), group]));
  const activeTopicKeys = new Set(jobTopics.filter(({ current }) => ACTIVE_STATUSES.has(current.status)).map(({ current }) => topicKey(current)));
  const currentJobs = jobTopics.map(({ current }) => current);
  const counts = {
    active: currentJobs.filter((job) => ACTIVE_STATUSES.has(job.status)).length,
    ready: currentJobs.filter((job) => job.status === 'READY').length,
    insufficient: currentJobs.filter((job) => job.status === 'INSUFFICIENT').length,
    failed: currentJobs.filter((job) => job.status === 'FAILED').length,
  };
  const cooldownActive = Boolean(overview?.provider_cooldown?.active && new Date(overview.provider_cooldown.cooldown_until).getTime() > Date.now());
  const clearFilters = () => { setQuery(''); setStatusFilter('ALL'); setTierFilter('ALL'); setFactorFilter('ALL'); setVisibilityFilter('ALL'); };
  const summarizeJobs = (jobs: AutoMedicalKnowledgeJob[]) => {
    const active = jobs.filter((job) => ACTIVE_STATUSES.has(job.status)).length;
    const ready = jobs.filter((job) => job.status === 'READY').length;
    const attention = jobs.filter((job) => job.status === 'FAILED' || job.status === 'INSUFFICIENT').length;
    return [`${ready} hoàn thành`, active ? `${active} đang xử lý` : null, attention ? `${attention} cần chú ý` : null].filter(Boolean).join(' · ');
  };
  const summarizeRevisions = (revisions: AutoMedicalKnowledgeRevision[]) => {
    const ready = revisions.filter((revision) => revision.generation_status === 'READY').length;
    const insufficient = revisions.length - ready;
    return [`${ready} có nội dung`, insufficient ? `${insufficient} chưa đủ bằng chứng` : null].filter(Boolean).join(' · ');
  };

  function renderAttempt(job: AutoMedicalKnowledgeJob, historical = false) {
    const status = AUTO_STATUS_PRESENTATIONS[job.status];
    return <article className={historical ? 'border-t border-slate-200 pt-3' : ''}>
      <div className="flex flex-wrap items-start justify-between gap-3"><FactorHeading topic={job} /><StatusBadge status={job.status} /></div>
      <p className="mt-2 text-xs leading-5 text-slate-600">{status.description}</p>
      {job.status === 'FAILED' ? <p className="mt-2 rounded-lg bg-red-50 p-2.5 text-sm text-red-800">{FAILURE_MESSAGES[job.last_error_code ?? ''] ?? 'Quy trình gặp lỗi kỹ thuật chưa xác định.'}</p> : null}
      {job.status === 'INSUFFICIENT' ? <p className="mt-2 rounded-lg bg-amber-50 p-2.5 text-sm text-amber-900">{INSUFFICIENT_MESSAGES[job.diagnostics?.insufficient_reason ?? ''] ?? 'Chưa có đủ bằng chứng phù hợp để tạo nội dung an toàn.'}</p> : null}
      {job.legacy ? <p className="mt-2 text-xs text-slate-500">Lịch sử cũ — chưa có đầy đủ dữ liệu chẩn đoán chi tiết.</p> : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-slate-500">Lần xử lý {job.attempt_count} · {new Date(job.created_at).toLocaleString('vi-VN')}</span>
        {canManage && job.status === 'FAILED' && !historical ? <button type="button" disabled={!overview?.settings.enabled || cooldownActive || busy !== null} onClick={() => void regenerate(job)} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><RotateCcw size={14} /> Thử lại</button> : null}
      </div>
      {!historical ? <DiscoveryDetails diagnostics={job.diagnostics} /> : null}
      {job.status === 'FAILED' ? <ValidationDetails job={job} /> : null}
    </article>;
  }
  function renderJob(group: JobTopic) {
    const compactHistory = group.current.history.filter((entry) => showLegacy || !entry.legacy);
    const previous = group.previous.filter((entry) => showLegacy || !entry.legacy);
    return <li key={topicKey(group.current)} className="rounded-xl border border-slate-200 p-3.5">
      {renderAttempt(group.current)}
      {compactHistory.length + previous.length > 0 ? <Disclosure title={`Lịch sử xử lý (${compactHistory.length + previous.length})`}>
        {compactHistory.map((entry) => <div key={`${entry.attempt}-${entry.created_at}`} className="border-t border-slate-200 pt-2 first:border-0 first:pt-0"><p className="font-semibold">Lần {entry.attempt} · {entry.status === 'FAILED' ? 'Có lỗi' : 'Không rõ trạng thái'}</p>{entry.failure_code ? <p>{FAILURE_MESSAGES[entry.failure_code] ?? entry.failure_code}</p> : null}{entry.legacy ? <p>Lịch sử cũ — chưa có đầy đủ dữ liệu chẩn đoán.</p> : null}</div>)}
        {previous.map((entry) => <div key={entry.id}>{renderAttempt(entry, true)}</div>)}
      </Disclosure> : null}
    </li>;
  }
  function renderRevision(revision: AutoMedicalKnowledgeRevision) {
    const tier = getAutoTierPresentation(revision);
    const visibility = revision.generation_status !== 'READY' ? null
      : revision.topic_hidden_by_staff
        ? { label: 'Đã ẩn bởi nhân viên', classes: 'border-slate-300 bg-slate-100 text-slate-700' }
        : overview?.settings.display_mode !== 'REVIEWED_WITH_AUTO_FALLBACK'
          ? { label: 'Auto đang tắt trên giao diện phụ huynh', classes: 'border-slate-300 bg-slate-100 text-slate-700' }
          : revision.auto_display_eligible
            ? { label: 'Đủ điều kiện hiển thị tự động', classes: 'border-emerald-200 bg-emerald-50 text-emerald-800' }
            : { label: 'Chưa đủ điều kiện hiển thị', classes: 'border-amber-200 bg-amber-50 text-amber-900' };
    return <li key={revision.id} className="rounded-xl border border-slate-200 p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3"><FactorHeading topic={revision} />{visibility ? <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${visibility.classes}`}>{visibility.label}</span> : null}</div>
      <div className="mt-3 flex flex-wrap gap-1.5"><StatusBadge status={revision.generation_status} />{tier ? <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-800">{tier.label}</span> : null}{tier ? <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">{tier.method}</span> : null}</div>
      {revision.generation_status === 'INSUFFICIENT' ? <p className="mt-3 rounded-lg bg-amber-50 p-2.5 text-sm text-amber-900">{INSUFFICIENT_MESSAGES[revision.diagnostics?.insufficient_reason ?? ''] ?? 'Chưa có đủ bằng chứng phù hợp để tạo nội dung an toàn.'}</p> : null}
      {tier?.label.includes('cơ bản') && (revision.strict_failure_code || revision.fallback_reason_code) ? <p className="mt-3 rounded-lg bg-amber-50 p-2.5 text-xs leading-5 text-amber-900">Bản kiểm tra nâng cao chưa hoàn thành; hệ thống đang dùng giải thích cơ bản an toàn.</p> : null}
      {revision.short_explanation_vi ? <p className="mt-3 text-sm leading-6 text-slate-700">{revision.short_explanation_vi}</p> : null}
      {revision.generation_status === 'READY' ? <p className="mt-2 text-xs text-slate-500">{revision.sources.length} nguồn · Mức bằng chứng: {revision.evidence_level}</p> : null}
      <Disclosure title="Xem nội dung và nguồn">
        {revision.detailed_explanation_vi ? <p className="text-sm leading-6 text-slate-700">{revision.detailed_explanation_vi}</p> : null}
        {revision.limitations_vi ? <p><strong>Giới hạn:</strong> {revision.limitations_vi}</p> : null}
        <p>Mức bằng chứng: {revision.evidence_level} · Revision {revision.revision_number}</p>
        <div className="space-y-2 pt-1">{revision.sources.length === 0 ? <p>Chưa có nguồn tham chiếu.</p> : revision.sources.map((source) => <article key={source.source_id} className="rounded-lg border border-slate-200 bg-white p-2.5">{source.url ? <a href={source.url} target="_blank" rel="noreferrer" className="font-semibold text-blue-700 underline decoration-blue-200 underline-offset-2">{source.title}</a> : <strong>{source.title}</strong>}<p className="mt-1 text-slate-500">{[source.journal, source.publication_year, source.pmid ? `PMID ${source.pmid}` : null].filter(Boolean).join(' · ')}</p></article>)}</div>
      </Disclosure>
      <DiscoveryDetails diagnostics={revision.diagnostics} />
      {(canManageVisibility || canManage) ? <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
        {revision.generation_status === 'READY' && canManageVisibility ? <button type="button" disabled={busy !== null} onClick={() => void run(`visibility-${revision.topic_id}`, () => setAutoMedicalKnowledgeTopicVisibility(revision.disease_group_id, revision, !revision.topic_hidden_by_staff), revision.topic_hidden_by_staff ? 'Đã hiển thị lại chủ đề.' : 'Đã ẩn chủ đề khỏi phụ huynh.')} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-800 disabled:opacity-50">{revision.topic_hidden_by_staff ? <Eye size={14} /> : <EyeOff size={14} />}{revision.topic_hidden_by_staff ? 'Hiển thị lại' : 'Ẩn khỏi phụ huynh'}</button> : null}
        {canManage ? <button type="button" disabled={!overview?.settings.enabled || cooldownActive || activeTopicKeys.has(topicKey(revision)) || busy !== null} onClick={() => void regenerate(revision)} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><RotateCcw size={14} /> Tạo lại</button> : null}
      </div> : null}
    </li>;
  }

  return <section aria-labelledby="auto-medical-heading" className="space-y-5">
    <header className="rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-start gap-3"><span className="rounded-xl bg-amber-100 p-2 text-amber-800"><ShieldAlert size={20} /></span><div><h2 id="auto-medical-heading" className="text-lg font-bold text-slate-950">Auto Medical Knowledge</h2><p className="mt-1 max-w-3xl text-sm leading-6 text-amber-950">Nội dung tự động chưa được kiểm duyệt y khoa. Việc hệ thống hiển thị tự động không phải là phê duyệt y khoa.</p></div></div><button type="button" onClick={() => void refresh()} disabled={loading || busy !== null} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 disabled:opacity-50"><RefreshCw size={15} /> Làm mới</button></div></header>
    {loading ? <p role="status" className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600"><Loader2 size={16} className="animate-spin" /> Đang tải hàng đợi Auto…</p> : null}
    {error ? <p role="alert" className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertTriangle size={16} /> {error}</p> : null}
    {notice ? <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
    {overview ? <>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.75fr)]">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-bold text-slate-950">Trạng thái hệ thống</h3><p className="mt-1 text-sm text-slate-600">{overview.settings.enabled ? 'Auto đang hoạt động và theo dõi hàng đợi.' : 'Auto đang tạm dừng. Nội dung và lịch sử đã có vẫn được giữ nguyên.'}</p></div>{canManage ? <button type="button" role="switch" aria-label="Bật hoặc tắt Auto Medical Knowledge" aria-checked={overview.settings.enabled} disabled={busy !== null} onClick={() => void toggleRuntime()} className={`inline-flex min-w-28 items-center justify-center rounded-full px-4 py-2 text-sm font-bold text-white disabled:opacity-50 ${overview.settings.enabled ? 'bg-emerald-700' : 'bg-slate-600'}`}>{overview.settings.enabled ? 'Tắt Auto' : 'Bật Auto'}</button> : null}</div><div className="mt-3 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">Chủ đề mới: {overview.settings.auto_visible_default ? 'hiển thị mặc định' : 'ẩn mặc định'}</span><span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">Giải thích cơ bản: {overview.settings.basic_fallback_enabled ? 'cho phép' : 'tắt'}</span></div>{cooldownActive && overview.provider_cooldown ? <p role="status" className="mt-3 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">{overview.provider_cooldown.provider} đang tạm nghỉ do giới hạn lượt gọi. Tiếp tục sau {new Date(overview.provider_cooldown.cooldown_until).toLocaleString('vi-VN')}.</p> : null}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"><label className="text-sm font-bold text-slate-900">Hiển thị cho phụ huynh<select aria-label="Chế độ hiển thị Auto cho Parent" value={overview.settings.display_mode} disabled={!canManage || busy !== null} onChange={(event) => void run('display-mode', () => updateAutoMedicalKnowledgeSettings({ display_mode: event.target.value as typeof overview.settings.display_mode }))} className="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-normal"><option value="REVIEWED_ONLY">Chỉ nội dung đã kiểm duyệt</option><option value="REVIEWED_WITH_AUTO_FALLBACK">Kiểm duyệt trước, Auto dự phòng</option></select></label><p className={`mt-2 rounded-lg p-2 text-xs ${overview.settings.display_mode === 'REVIEWED_WITH_AUTO_FALLBACK' ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-100 text-slate-700'}`}>{overview.settings.display_mode === 'REVIEWED_WITH_AUTO_FALLBACK' ? 'Parent Auto đang bật: nội dung đủ điều kiện có thể được dùng khi chưa có bản kiểm duyệt.' : 'Parent Auto đang tắt: phụ huynh không nhận nội dung Auto.'}</p><label className="mt-3 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" aria-label="Cho phép Giải thích cơ bản khi Kiểm tra nâng cao không hoàn thành" checked={overview.settings.basic_fallback_enabled} disabled={!canManage || busy !== null} onChange={(event) => void run('basic-setting', () => updateAutoMedicalKnowledgeSettings({ basic_fallback_enabled: event.target.checked }))} /><span><strong>Cho phép giải thích cơ bản</strong><span className="mt-0.5 block text-xs text-slate-500">Dùng bản an toàn khi kiểm tra nâng cao không hoàn thành.</span></span></label></section>
      </div>
      <section><h3 className="mb-3 font-bold text-slate-950">Tổng quan chủ đề</h3><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
        ['Đang xử lý', counts.active, Clock3, 'bg-blue-50 text-blue-700'], ['Hoàn thành', counts.ready, CheckCircle2, 'bg-emerald-50 text-emerald-700'], ['Chưa đủ bằng chứng', counts.insufficient, Search, 'bg-amber-50 text-amber-800'], ['Có lỗi', counts.failed, AlertTriangle, 'bg-red-50 text-red-700'],
      ].map(([label, count, Icon, color]) => { const ItemIcon = Icon as typeof Clock3; return <article key={label as string} className={`rounded-2xl border border-slate-200 p-4 ${color}`}><div className="flex items-center justify-between"><ItemIcon size={19} /><strong className="text-2xl text-slate-950">{count as number}</strong></div><p className="mt-3 text-sm font-semibold text-slate-700">{label as string}</p></article>; })}</div></section>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2"><Filter size={17} /><h3 className="font-bold">Tìm và lọc chủ đề</h3></div><div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><label className="relative sm:col-span-2 xl:col-span-1"><span className="sr-only">Tìm chủ đề Auto</span><Search size={15} className="absolute left-3 top-3 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Tìm chủ đề Auto" placeholder="Tìm theo tên bệnh, mã bệnh hoặc yếu tố…" className="w-full rounded-xl border border-slate-300 py-2.5 pl-9 pr-3 text-sm" /></label><select aria-label="Lọc trạng thái Auto" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi trạng thái</option>{Object.entries(AUTO_STATUS_PRESENTATIONS).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}</select><select aria-label="Lọc mức Auto" value={tierFilter} onChange={(event) => setTierFilter(event.target.value as TierFilter)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi mức tạo</option><option value="STRICT">Kiểm tra nâng cao</option><option value="BASIC">Giải thích cơ bản</option><option value="INSUFFICIENT">Chưa đủ bằng chứng</option></select><select aria-label="Lọc nhóm yếu tố Auto" value={factorFilter} onChange={(event) => setFactorFilter(event.target.value as FactorFilter)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi nhóm yếu tố</option>{(Object.keys(FACTOR_FILTER_LABELS) as MedicalFactorType[]).map((value) => <option key={value} value={value}>{FACTOR_FILTER_LABELS[value]}</option>)}</select><select aria-label="Lọc hiển thị Auto" value={visibilityFilter} onChange={(event) => setVisibilityFilter(event.target.value as VisibilityFilter)} className="rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"><option value="ALL">Mọi trạng thái hiển thị</option><option value="VISIBLE">Đủ điều kiện hiển thị</option><option value="HIDDEN">Đã ẩn</option><option value="INELIGIBLE">Chưa đủ điều kiện</option></select></div><label className="mt-3 inline-flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={showLegacy} onChange={(event) => setShowLegacy(event.target.checked)} /> Hiện lịch sử cũ</label></section>
      <div className="grid gap-5 xl:grid-cols-2 xl:items-start">
        <section aria-labelledby="auto-processing-heading" className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5"><div className="flex items-start justify-between gap-3"><div><h3 id="auto-processing-heading" className="font-bold text-slate-950">Xử lý và trạng thái</h3><p className="mt-1 text-xs text-slate-500">{visibleJobs.length} chủ đề trong {jobDiseaseGroups.length} nhóm bệnh</p></div><Clock3 size={18} /></div><div className="mt-4 space-y-3">{jobDiseaseGroups.length === 0 ? <EmptyState onReset={clearFilters}>Không có tiến trình phù hợp bộ lọc.</EmptyState> : jobDiseaseGroups.map((group, index) => <DiseaseSection key={group.id} group={group} defaultOpen={index === 0} statusSummary={summarizeJobs(group.items)}><ul className="space-y-3">{group.items.map((job) => renderJob(jobsByKey.get(topicKey(job))!))}</ul></DiseaseSection>)}</div></section>
        <section aria-labelledby="auto-content-heading" className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5"><div className="flex items-start justify-between gap-3"><div><h3 id="auto-content-heading" className="font-bold text-slate-950">Nội dung hiện tại</h3><p className="mt-1 text-xs text-slate-500">{visibleRevisions.length} chủ đề trong {revisionDiseaseGroups.length} nhóm bệnh</p></div><Bot size={18} /></div><div className="mt-4 space-y-3">{revisionDiseaseGroups.length === 0 ? <EmptyState onReset={clearFilters}>Chưa có nội dung Auto phù hợp bộ lọc.</EmptyState> : revisionDiseaseGroups.map((group, index) => <DiseaseSection key={group.id} group={group} defaultOpen={index === 0} statusSummary={summarizeRevisions(group.items)}><ul className="space-y-3">{group.items.map(renderRevision)}</ul></DiseaseSection>)}</div></section>
      </div>
    </> : null}
  </section>;
}
