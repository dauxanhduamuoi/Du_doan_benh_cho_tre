import { useEffect, useState } from 'react';
import { History, Loader2, Sparkles } from 'lucide-react';
import {
  generateMedicalKnowledgeDraft,
  getMedicalKnowledgeDraftHistory,
  getMedicalKnowledgeRevision,
  medicalKnowledgeDraftErrorMessage,
  updateMedicalKnowledgeDraft,
  type DraftRevision,
  type DraftRevisionPatch,
  type DraftTopicHistory,
} from '@/lib/medicalKnowledgeApi';
import MedicalDraftReviewForm from './MedicalDraftReviewForm';

interface Props {
  diseaseGroupId: string;
  weatherFactor: string;
  importedSourceIds: number[];
  llmAvailable: boolean;
}

export default function MedicalDraftWorkspace({
  diseaseGroupId,
  weatherFactor,
  importedSourceIds,
  llmAvailable,
}: Props) {
  const validGenerationSourceCount = importedSourceIds.length >= 1 && importedSourceIds.length <= 8;
  const [history, setHistory] = useState<DraftTopicHistory | null>(null);
  const [activeRevision, setActiveRevision] = useState<DraftRevision | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [opening, setOpening] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function loadHistory(cancelled?: () => boolean) {
    const response = await getMedicalKnowledgeDraftHistory(diseaseGroupId, weatherFactor);
    if (!cancelled?.()) setHistory(response);
  }

  useEffect(() => {
    setActiveRevision(null);
    setHistory(null);
    setError(null);
    setSuccess(null);
    if (!diseaseGroupId || !weatherFactor) return;
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
  }, [diseaseGroupId, weatherFactor]);

  async function generateDraft() {
    if (!importedSourceIds.length || generating) return;
    setGenerating(true);
    setError(null);
    setSuccess(null);
    try {
      const revision = await generateMedicalKnowledgeDraft({
        disease_group_id: diseaseGroupId,
        weather_factor: weatherFactor,
        source_ids: importedSourceIds,
      });
      setActiveRevision(revision);
      await loadHistory();
    } catch (reason) {
      setError(medicalKnowledgeDraftErrorMessage(reason));
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

  if (!diseaseGroupId || !weatherFactor) return null;

  return (
    <div className="space-y-5">
      {!llmAvailable && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Tạo bản nháp bằng AI chưa được cấu hình trên máy chủ.
        </div>
      )}

      {llmAvailable && importedSourceIds.length > 0 && (
        <section className="rounded-2xl border border-violet-200 bg-gradient-to-r from-violet-50 to-blue-50 p-4 sm:p-5">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <h2 className="font-bold text-slate-900">Tạo đề xuất để nhân viên y tế xem xét</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                AI tạo bản nháp dựa trên thông tin và tóm tắt của {importedSourceIds.length} tài liệu PubMed đã chọn.
              </p>
              {!validGenerationSourceCount && (
                <p className="mt-1 text-sm font-medium text-red-700">Mỗi bản nháp chỉ sử dụng từ 1 đến 8 nguồn; hãy chọn và nhập lại một tập nguồn nhỏ hơn.</p>
              )}
            </div>
            <button
              type="button"
              onClick={generateDraft}
              disabled={generating || !validGenerationSourceCount}
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-violet-700 px-5 py-3 text-sm font-bold text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {generating ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}
              {generating ? 'Đang tạo bản nháp…' : 'Tạo bản nháp bằng AI'}
            </button>
          </div>
          {generating && (
            <p role="status" aria-live="polite" className="mt-3 text-sm font-medium text-violet-800">
              AI đang đọc tóm tắt của các tài liệu đã chọn và tạo bản nháp…
            </p>
          )}
        </section>
      )}

      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {success && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{success}</div>}

      <section aria-labelledby="draft-history-heading" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <h2 id="draft-history-heading" className="flex items-center gap-2 font-bold text-slate-900"><History size={18} /> Các phiên bản</h2>
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
      </section>

      {activeRevision && (
        <MedicalDraftReviewForm revision={activeRevision} saving={saving} onSave={saveDraft} />
      )}
    </div>
  );
}
