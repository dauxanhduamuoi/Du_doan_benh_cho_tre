import { useEffect, useState } from 'react';
import { History, Loader2, Sparkles, X } from 'lucide-react';
import { ApiError } from '@/lib/api';
import {
  generateMedicalKnowledgeDraft,
  approveMedicalKnowledgeRevision,
  getMedicalKnowledgeDraftHistory,
  getMedicalKnowledgeRevision,
  medicalKnowledgeDraftErrorMessage,
  medicalKnowledgeApprovalErrorMessage,
  medicalKnowledgePublicationErrorMessage,
  medicalKnowledgeUnpublicationErrorMessage,
  publishMedicalKnowledgeRevision,
  unpublishMedicalKnowledgeRevision,
  updateMedicalKnowledgeDraft,
  type DraftRevision,
  type DraftRevisionPatch,
  type DraftTopicHistory,
  type TopicSourceLibraryItem,
  evidenceContentLabel,
  MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES,
} from '@/lib/medicalKnowledgeApi';
import MedicalDraftReviewForm from './MedicalDraftReviewForm';
import { factorIsComplete, factorTopicKey, type MedicalFactorSelector } from '@/lib/medicalKnowledgeFactors';

interface Props {
  diseaseGroupId: string;
  factor: MedicalFactorSelector | null;
  selectedSources: TopicSourceLibraryItem[];
  onRemoveSelectedSource: (sourceId: number) => void;
  onInvalidSelection: () => void;
  llmAvailable: boolean;
  canApprove: boolean;
  canPublish: boolean;
  canUnpublish: boolean;
  compactSourceSummary?: boolean;
}

export default function MedicalDraftWorkspace({
  diseaseGroupId,
  factor,
  selectedSources,
  onRemoveSelectedSource,
  onInvalidSelection,
  llmAvailable,
  canApprove,
  canPublish,
  canUnpublish,
  compactSourceSummary = false,
}: Props) {
  const validGenerationSourceCount = selectedSources.length >= 1
    && selectedSources.length <= MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES;
  const [history, setHistory] = useState<DraftTopicHistory | null>(null);
  const [activeRevision, setActiveRevision] = useState<DraftRevision | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [opening, setOpening] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [unpublishing, setUnpublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  async function loadHistory(cancelled?: () => boolean) {
    if (!factorIsComplete(factor)) return;
    const response = await getMedicalKnowledgeDraftHistory(diseaseGroupId, factor);
    if (!cancelled?.()) setHistory(response);
  }

  useEffect(() => {
    setActiveRevision(null);
    setHistory(null);
    setError(null);
    setSuccess(null);
    if (!diseaseGroupId || !factorIsComplete(factor)) return;
    let cancelled = false;
    setHistoryLoading(true);
    loadHistory(() => cancelled)
      .catch((reason) => {
        if (!cancelled) setError(medicalKnowledgeDraftErrorMessage(reason));
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => { cancelled = true; };
  }, [diseaseGroupId, factorTopicKey(diseaseGroupId, factor)]);

  async function generateDraft() {
    if (!selectedSources.length || generating || !factorIsComplete(factor)) return;
    setGenerating(true);
    setError(null);
    setSuccess(null);
    try {
      const revision = await generateMedicalKnowledgeDraft({
        disease_group_id: diseaseGroupId,
        ...factor,
        source_ids: selectedSources.map((source) => source.source_id),
      });
      setActiveRevision(revision);
      await loadHistory();
    } catch (reason) {
      setError(medicalKnowledgeDraftErrorMessage(reason));
      if (reason instanceof ApiError && [
        'DRAFT_SOURCE_NOT_IN_TOPIC',
        'DRAFT_SOURCE_NOT_FOUND',
        'DRAFT_SOURCE_NO_USABLE_EVIDENCE',
        'DRAFT_SOURCE_EVIDENCE_MISMATCH',
        'DRAFT_TOPIC_MISMATCH',
      ].includes(reason.code ?? '')) {
        onInvalidSelection();
      }
    } finally {
      setGenerating(false);
    }
  }

  async function openRevision(revisionId: number) {
    setOpening(revisionId);
    setError(null);
    setSuccess(null);
    try {
      setActiveRevision(await getMedicalKnowledgeRevision(revisionId));
    } catch (reason) {
      setError(medicalKnowledgeDraftErrorMessage(reason));
    } finally {
      setOpening(null);
    }
  }

  async function saveDraft(payload: DraftRevisionPatch) {
    if (!activeRevision || saving) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const revision = await updateMedicalKnowledgeDraft(activeRevision.id, payload);
      setActiveRevision(revision);
      setSuccess('Đã lưu bản nháp. Nội dung này chưa hiển thị cho phụ huynh.');
      await loadHistory();
    } catch (reason) {
      setError(medicalKnowledgeDraftErrorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function approveRevision() {
    if (!activeRevision || activeRevision.status !== 'DRAFT' || approving) return;
    setApproving(true);
    setError(null);
    setSuccess(null);
    try {
      await approveMedicalKnowledgeRevision(activeRevision.id);
      const approvedRevision = await getMedicalKnowledgeRevision(activeRevision.id);
      setActiveRevision(approvedRevision);
      setSuccess('Đã duyệt phiên bản. Nội dung vẫn chưa được xuất bản cho phụ huynh.');
      await loadHistory();
    } catch (reason) {
      setError(medicalKnowledgeApprovalErrorMessage(reason));
    } finally {
      setApproving(false);
    }
  }

  async function publishRevision() {
    if (!activeRevision || activeRevision.status !== 'APPROVED' || activeRevision.is_published || publishing) return;
    setPublishing(true);
    setError(null);
    setSuccess(null);
    try {
      await publishMedicalKnowledgeRevision(activeRevision.id);
      const publishedRevision = await getMedicalKnowledgeRevision(activeRevision.id);
      setActiveRevision(publishedRevision);
      await loadHistory();
      setSuccess('Đã xuất bản phiên bản làm bản kiến thức chính thức hiện tại của chủ đề.');
    } catch (reason) {
      setError(medicalKnowledgePublicationErrorMessage(reason));
    } finally {
      setPublishing(false);
    }
  }

  async function unpublishRevision() {
    const isCurrent = activeRevision && (
      activeRevision.is_published
      || history?.topic?.published_revision_id === activeRevision.id
    );
    if (!activeRevision || activeRevision.status !== 'APPROVED' || !isCurrent || unpublishing) return;
    setUnpublishing(true);
    setError(null);
    setSuccess(null);
    try {
      await unpublishMedicalKnowledgeRevision(activeRevision.id);
      const approvedRevision = await getMedicalKnowledgeRevision(activeRevision.id);
      setActiveRevision(approvedRevision);
      await loadHistory();
      setSuccess('Đã ngừng xuất bản phiên bản. Phiên bản vẫn được giữ ở trạng thái Đã duyệt và không bị xóa.');
    } catch (reason) {
      setError(medicalKnowledgeUnpublicationErrorMessage(reason));
    } finally {
      setUnpublishing(false);
    }
  }

  if (!diseaseGroupId || !factorIsComplete(factor)) return null;

  return (
    <div className="space-y-5">
      {!llmAvailable && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Tạo bản nháp bằng AI chưa được cấu hình trên máy chủ.
        </div>
      )}

      {llmAvailable && (
        <section className="rounded-2xl border border-violet-200 bg-gradient-to-r from-violet-50 to-blue-50 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
            <h2 className="font-bold text-slate-900">Nguồn sẽ dùng cho bản nháp</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              {compactSourceSummary
                ? 'Danh sách chi tiết nằm trong tab “Nguồn AI sẽ đọc” ở không gian nguồn.'
                : 'AI chỉ đọc những tài liệu bạn chọn bên dưới. Các tài liệu khác trong kho không tự động được sử dụng.'}
            </p>
            </div>
            <span className="shrink-0 rounded-full bg-violet-100 px-3 py-1 text-xs font-bold text-violet-900">{selectedSources.length} tài liệu</span>
          </div>

          {compactSourceSummary && selectedSources.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {selectedSources.map((source) => <span key={source.source_id} className="max-w-full truncate rounded-lg border border-violet-200 bg-white/80 px-2.5 py-1.5 text-xs font-medium text-slate-700">{source.title}</span>)}
            </div>
          )}

          {!compactSourceSummary && (selectedSources.length > 0 ? (
            <div className="mt-3 space-y-2">
              {selectedSources.map((source) => (
                <div key={source.source_id} className="flex items-start justify-between gap-3 rounded-xl border border-violet-200 bg-white/80 p-3">
                  <div className="min-w-0">
                    <p className="font-semibold text-slate-900">{source.title}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {source.pmid ? `PMID: ${source.pmid}` : `Source ID: ${source.source_id}`}
                      {source.pmcid ? ` · PMCID: ${source.pmcid}` : ''}
                    </p>
                    <p className="mt-1 text-xs font-medium text-violet-800">{evidenceContentLabel(source.content_kind)}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onRemoveSelectedSource(source.source_id)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    aria-label={`Bỏ nguồn ${source.pmid ?? source.title}`}
                  >
                    <X size={13} /> Bỏ
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-xl bg-white/70 px-3 py-2 text-sm text-slate-600">
              Hãy chọn ít nhất 1 nguồn trong kho chủ đề.
            </p>
          ))}

          {compactSourceSummary && selectedSources.length === 0 && (
            <p className="mt-3 rounded-xl bg-white/70 px-3 py-2 text-sm text-slate-600">Chưa có nguồn. Chọn nguồn ở workspace bên trái trước khi tạo bản nháp.</p>
          )}

          <div className="mt-4 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <h2 className="font-bold text-slate-900">Tạo đề xuất để nhân viên y tế xem xét</h2>
              {!validGenerationSourceCount && (
                <p className="mt-1 text-sm font-medium text-red-700">Mỗi bản nháp chỉ sử dụng từ 1 đến 10 nguồn.</p>
              )}
            </div>
            <button
              type="button"
              onClick={generateDraft}
              aria-label="Tạo bản nháp bằng AI"
              disabled={generating || !validGenerationSourceCount}
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-violet-700 px-5 py-3 text-sm font-bold text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {generating ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}
              {generating
                ? 'Đang tạo bản nháp…'
                : selectedSources.length > 0
                  ? `Tạo bản nháp bằng AI từ ${selectedSources.length} nguồn`
                  : 'Tạo bản nháp bằng AI'}
            </button>
          </div>
          {generating && (
            <p role="status" aria-live="polite" className="mt-3 text-sm font-medium text-violet-800">
              AI đang đọc evidence content đã lưu của các tài liệu đã chọn và tạo bản nháp…
            </p>
          )}
        </section>
      )}

      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {success && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</div>}

      <section aria-labelledby="draft-history-heading" className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <button type="button" aria-expanded={historyOpen} aria-controls="draft-history-content" onClick={() => setHistoryOpen((value) => !value)} className="flex w-full cursor-pointer items-center justify-between gap-3 p-4 text-left font-bold text-slate-900 sm:p-5">
          <span className="flex items-center gap-2"><History size={18} /> Lịch sử phiên bản</span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">{history?.revisions.length ?? 0}</span>
        </button>
        <div id="draft-history-content" className={`overflow-hidden border-slate-200 px-4 transition-all sm:px-5 ${historyOpen ? 'max-h-[32rem] border-t pb-4 opacity-100 sm:pb-5' : 'max-h-0 opacity-0'}`}>
        {historyLoading ? (
          <p role="status" className="mt-3 flex items-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" /> Đang tải lịch sử…</p>
        ) : history && history.revisions.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {history.revisions.map((revision) => (
              <button
                key={revision.id}
                type="button"
                onClick={() => openRevision(revision.id)}
                disabled={opening !== null}
                className="rounded-xl border border-slate-200 px-3 py-2 text-left text-sm hover:border-blue-300 hover:bg-blue-50 disabled:opacity-60"
              >
                Revision {revision.revision_number} — {revision.status}
                {opening === revision.id ? ' · Đang mở…' : ''}
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-500">Chưa có bản nháp cho nhóm bệnh và yếu tố này.</p>
        )}
        </div>
      </section>

      {activeRevision && (
        <MedicalDraftReviewForm
          revision={activeRevision}
          saving={saving}
          approving={approving}
          publishing={publishing}
          unpublishing={unpublishing}
          canApprove={canApprove}
          canPublish={canPublish}
          canUnpublish={canUnpublish}
          currentPublishedRevisionId={history?.topic?.published_revision_id ?? null}
          onSave={saveDraft}
          onApprove={approveRevision}
          onPublish={publishRevision}
          onUnpublish={unpublishRevision}
        />
      )}
    </div>
  );
}
