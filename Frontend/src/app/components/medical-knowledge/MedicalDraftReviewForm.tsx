import { useEffect, useState, type FormEvent } from 'react';
import { BookOpen, EyeOff, Loader2, Save, Send, ShieldCheck } from 'lucide-react';
import type {
  DraftRevision,
  DraftRevisionPatch,
  EvidenceLevel,
  EvidenceScope,
  PopulationRelevance,
} from '@/lib/medicalKnowledgeApi';
import { evidenceContentLabel } from '@/lib/medicalKnowledgeApi';

interface Props {
  revision: DraftRevision;
  saving: boolean;
  approving: boolean;
  publishing: boolean;
  unpublishing: boolean;
  canApprove: boolean;
  canPublish: boolean;
  canUnpublish: boolean;
  currentPublishedRevisionId: number | null;
  onSave: (payload: DraftRevisionPatch) => void;
  onApprove: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
}

const evidenceLevels: EvidenceLevel[] = [
  'SUPPORTED',
  'LIMITED_OR_INDIRECT',
  'CONFLICTING',
  'INSUFFICIENT',
];

const evidenceScopes: Array<{ value: EvidenceScope; label: string }> = [
  { value: 'WHOLE_GROUP', label: 'WHOLE_GROUP — Bằng chứng phù hợp với phạm vi nhóm bệnh' },
  { value: 'PARTIAL_GROUP', label: 'PARTIAL_GROUP — Bằng chứng chủ yếu áp dụng cho một phần của nhóm' },
];

const populationLabels: Record<PopulationRelevance, string> = {
  PEDIATRIC_DIRECT: 'Đúng đối tượng trẻ em',
  MIXED_AGE: 'Nghiên cứu nhiều độ tuổi',
  ADULT_ONLY: 'Chỉ người lớn',
  ELDERLY_ONLY: 'Chỉ người cao tuổi',
  UNKNOWN: 'Chưa xác định đối tượng',
};

const populationBadgeStyles: Record<PopulationRelevance, string> = {
  PEDIATRIC_DIRECT: 'bg-emerald-100 text-emerald-800',
  MIXED_AGE: 'bg-sky-100 text-sky-800',
  ADULT_ONLY: 'bg-amber-100 text-amber-800',
  ELDERLY_ONLY: 'bg-orange-100 text-orange-800',
  UNKNOWN: 'bg-slate-200 text-slate-700',
};

function parentEligibilityReason(reason: string): string {
  if (reason === 'PARENT_TIER2_EVIDENCE_LEVEL_NOT_DISPLAYABLE') {
    return 'Mức bằng chứng hiện tại không được phép hiển thị ở Tier 2.';
  }
  if (reason === 'PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED') {
    return 'Thiếu nguồn vừa hỗ trợ trực tiếp quan hệ bệnh–thời tiết vừa nghiên cứu trực tiếp trên trẻ em.';
  }
  return 'Assessment nguồn chưa đầy đủ hoặc không hợp lệ.';
}

export default function MedicalDraftReviewForm({
  revision,
  saving,
  approving,
  publishing,
  unpublishing,
  canApprove,
  canPublish,
  canUnpublish,
  currentPublishedRevisionId,
  onSave,
  onApprove,
  onPublish,
  onUnpublish,
}: Props) {
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [publishConfirmationOpen, setPublishConfirmationOpen] = useState(false);
  const [unpublishConfirmationOpen, setUnpublishConfirmationOpen] = useState(false);
  const [form, setForm] = useState<DraftRevisionPatch>({
    evidence_level: revision.evidence_level,
    evidence_scope: revision.evidence_scope,
    short_explanation_vi: revision.short_explanation_vi,
    detailed_explanation_vi: revision.detailed_explanation_vi,
    limitations_vi: revision.limitations_vi,
  });

  useEffect(() => {
    setForm({
      evidence_level: revision.evidence_level,
      evidence_scope: revision.evidence_scope,
      short_explanation_vi: revision.short_explanation_vi,
      detailed_explanation_vi: revision.detailed_explanation_vi,
      limitations_vi: revision.limitations_vi,
    });
    setConfirmationOpen(false);
    setPublishConfirmationOpen(false);
    setUnpublishConfirmationOpen(false);
  }, [revision]);

  const editable = revision.status === 'DRAFT';
  const isPublished = revision.is_published === true || currentPublishedRevisionId === revision.id;
  const replacesCurrent = currentPublishedRevisionId !== null && currentPublishedRevisionId !== revision.id;
  const canSave = editable && !saving && Boolean(
    form.short_explanation_vi.trim() &&
      form.detailed_explanation_vi.trim() &&
      form.limitations_vi.trim(),
  );
  const hasPediatricDirectSupport = revision.sources.some((source) =>
    source.population_relevance === 'PEDIATRIC_DIRECT'
      && source.relevance_note?.startsWith('DIRECT:'),
  );
  const fallbackEligibilityReasons = [
    ...(!['SUPPORTED', 'LIMITED_OR_INDIRECT'].includes(form.evidence_level)
      ? ['PARENT_TIER2_EVIDENCE_LEVEL_NOT_DISPLAYABLE']
      : []),
    ...(!hasPediatricDirectSupport ? ['PARENT_TIER2_PEDIATRIC_SUPPORT_REQUIRED'] : []),
  ];
  const parentEligibilityReasons = editable
    ? fallbackEligibilityReasons
    : revision.parent_tier2_ineligibility_reasons ?? fallbackEligibilityReasons;
  const parentTier2Eligible = editable
    ? parentEligibilityReasons.length === 0
    : revision.parent_tier2_eligible ?? parentEligibilityReasons.length === 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSave) onSave(form);
  }

  const approvedAt = revision.reviewed_at
    ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(
      new Date(revision.reviewed_at),
    )
    : null;
  const publishedAt = revision.published_at
    ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(
      new Date(revision.published_at),
    )
    : null;

  return (
    <section aria-labelledby="medical-draft-heading" className="rounded-2xl border border-blue-200 bg-white shadow-sm">
      <div className="border-b border-blue-100 bg-blue-50/70 p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">Bản nháp giải thích y khoa</p>
            <h2 id="medical-draft-heading" className="mt-1 text-lg font-bold text-slate-900">
              Revision {revision.revision_number}
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
          <span className={`rounded-full px-3 py-1 text-xs font-bold ${
            revision.status === 'DRAFT'
              ? 'bg-amber-100 text-amber-800'
              : revision.status === 'APPROVED'
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-slate-200 text-slate-700'
          }`}>
            {revision.status === 'APPROVED'
              ? 'APPROVED — Đã duyệt'
              : revision.status === 'DRAFT'
                ? 'DRAFT — Chưa xuất bản'
                : `${revision.status} — Chỉ đọc`}
          </span>
          {isPublished && (
            <span className="rounded-full bg-blue-700 px-3 py-1 text-xs font-bold text-white">
              ĐANG XUẤT BẢN
            </span>
          )}
          </div>
        </div>
        <dl className="mt-4 grid gap-2 text-sm text-slate-700 sm:grid-cols-3">
          <div><dt className="font-semibold">Nhóm bệnh</dt><dd>{revision.disease_group_name}</dd></div>
          <div><dt className="font-semibold">Yếu tố thời tiết</dt><dd>{revision.weather_factor}</dd></div>
          <div><dt className="font-semibold">Nguồn đã sử dụng</dt><dd>{revision.sources.length} tài liệu PubMed</dd></div>
        </dl>
        {revision.status === 'APPROVED' && (
          <div className="mt-3 space-y-1 text-sm text-emerald-800">
          <p>
            Duyệt bởi <span className="font-semibold">{
              revision.reviewed_by_name
                ?? (revision.reviewed_by ? `Người dùng #${revision.reviewed_by}` : 'Không có thông tin')
            }</span>
            {approvedAt ? ` · ${approvedAt}` : ''}
          </p>
          {isPublished && (
            <p>
              Xuất bản bởi <span className="font-semibold">{
                revision.published_by_name
                  ?? (revision.published_by ? `Người dùng #${revision.published_by}` : 'Không có thông tin')
              }</span>
              {publishedAt ? ` · ${publishedAt}` : ''}
            </p>
          )}
          </div>
        )}
      </div>

      <div className={`mx-4 mt-4 rounded-xl border p-4 text-sm sm:mx-6 ${
        parentTier2Eligible
          ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
          : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}>
        <p className="font-bold">
          {parentTier2Eligible
            ? 'Đủ điều kiện nội dung Tier 2 cho phụ huynh'
            : 'Chưa đủ điều kiện nội dung Tier 2 cho phụ huynh'}
        </p>
        {!parentTier2Eligible && (
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {parentEligibilityReasons.map((reason) => (
              <li key={reason}>{parentEligibilityReason(reason)}</li>
            ))}
          </ul>
        )}
      </div>

      {!hasPediatricDirectSupport && (
        <div role="alert" className="mx-4 mt-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800 sm:mx-6">
          Cảnh báo: chưa có nguồn PEDIATRIC_DIRECT hỗ trợ trực tiếp quan hệ bệnh–thời tiết.
        </div>
      )}

      <div className={`m-4 rounded-xl border p-4 text-sm leading-6 sm:m-6 ${
        revision.status === 'APPROVED'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
          : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}>
        {revision.status === 'APPROVED'
          ? isPublished
            ? 'Phiên bản này đã được duyệt, khóa chỉnh sửa và đang là bản kiến thức chính thức hiện tại của chủ đề.'
            : 'Phiên bản này đã được duyệt và đang được khóa để giữ lịch sử. Chưa được xuất bản cho phụ huynh.'
          : 'Bản nháp được AI tạo từ evidence content đã lưu của các nguồn được chọn. Nhân viên y tế cần kiểm tra nội dung và nguồn trước khi duyệt.'}
      </div>

      <form onSubmit={submit} className="space-y-5 p-4 pt-0 sm:p-6 sm:pt-0">
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="draft-evidence-level" className="mb-1.5 block text-sm font-semibold text-slate-800">
              Mức bằng chứng AI đề xuất
            </label>
            <select
              id="draft-evidence-level"
              value={form.evidence_level}
              disabled={!editable}
              onChange={(event) => setForm({ ...form, evidence_level: event.target.value as EvidenceLevel })}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm disabled:bg-slate-100"
            >
              {evidenceLevels.map((level) => <option key={level} value={level}>{level}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="draft-evidence-scope" className="mb-1.5 block text-sm font-semibold text-slate-800">
              Phạm vi bằng chứng AI đề xuất
            </label>
            <select
              id="draft-evidence-scope"
              value={form.evidence_scope}
              disabled={!editable}
              onChange={(event) => setForm({ ...form, evidence_scope: event.target.value as EvidenceScope })}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm disabled:bg-slate-100"
            >
              {evidenceScopes.map((scope) => <option key={scope.value} value={scope.value}>{scope.label}</option>)}
            </select>
          </div>
        </div>

        {([
          ['short_explanation_vi', 'Giải thích ngắn', 3],
          ['detailed_explanation_vi', 'Giải thích chi tiết', 6],
          ['limitations_vi', 'Giới hạn', 4],
        ] as const).map(([field, label, rows]) => (
          <div key={field}>
            <label htmlFor={`draft-${field}`} className="mb-1.5 block text-sm font-semibold text-slate-800">{label}</label>
            <textarea
              id={`draft-${field}`}
              rows={rows}
              value={form[field]}
              readOnly={!editable}
              onChange={(event) => setForm({ ...form, [field]: event.target.value })}
              className="w-full resize-y rounded-xl border border-slate-300 px-3 py-2.5 text-sm leading-6 read-only:bg-slate-100"
            />
          </div>
        ))}

        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900"><BookOpen size={17} /> Nguồn</h3>
          <div className="mt-3 space-y-3">
            {revision.sources.map((source) => (
              <article key={source.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
                <h4 className="font-semibold text-slate-900">{source.title}</h4>
                <p className="mt-1 text-slate-600">
                  PMID {source.pmid ?? 'Không có'}
                  {source.publication_year ? ` · ${source.publication_year}` : ''}
                  {source.journal ? ` · ${source.journal}` : ''}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded-full bg-violet-100 px-2.5 py-1 font-semibold text-violet-800">
                    {evidenceContentLabel(source.content_kind)}
                  </span>
                  {source.pmcid && <span className="font-medium text-slate-600">{source.pmcid}</span>}
                  {(() => {
                    const population = source.population_relevance ?? 'UNKNOWN';
                    return (
                      <span className={`rounded-full px-2.5 py-1 font-semibold ${populationBadgeStyles[population]}`}>
                        {populationLabels[population]}
                      </span>
                    );
                  })()}
                </div>
                {source.relevance_note && <p className="mt-2 leading-6 text-blue-800">{source.relevance_note}</p>}
                <p className="mt-2 leading-6 text-slate-700">
                  <span className="font-semibold">Đánh giá nhóm tuổi:</span>{' '}
                  {source.population_note || 'Revision này chưa lưu đánh giá nhóm tuổi (UNKNOWN).'}
                </p>
              </article>
            ))}
          </div>
        </div>

        {editable && (
          <div className="flex flex-col gap-3 sm:flex-row">
            <button
              type="submit"
              disabled={!canSave || approving}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 px-5 py-3 text-sm font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
            >
              <Save size={17} /> {saving ? 'Đang lưu bản nháp…' : 'Lưu bản nháp'}
            </button>
            {canApprove && (
              <button
                type="button"
                onClick={() => setConfirmationOpen(true)}
                disabled={saving || approving}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
              >
                {approving ? <Loader2 size={17} className="animate-spin" /> : <ShieldCheck size={17} />}
                {approving ? 'Đang duyệt…' : 'Duyệt bản này'}
              </button>
            )}
          </div>
        )}
      </form>

      {revision.status === 'APPROVED' && !isPublished && canPublish && (
        <div className="px-4 pb-5 sm:px-6 sm:pb-6">
          <button
            type="button"
            onClick={() => setPublishConfirmationOpen(true)}
            disabled={publishing}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 px-5 py-3 text-sm font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            {publishing ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
            {publishing ? 'Đang xuất bản…' : 'Xuất bản bản này'}
          </button>
        </div>
      )}

      {revision.status === 'APPROVED' && isPublished && canUnpublish && (
        <div className="px-4 pb-5 sm:px-6 sm:pb-6">
          <button
            type="button"
            onClick={() => setUnpublishConfirmationOpen(true)}
            disabled={unpublishing}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-rose-300 bg-white px-5 py-3 text-sm font-bold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            {unpublishing ? <Loader2 size={17} className="animate-spin" /> : <EyeOff size={17} />}
            {unpublishing ? 'Đang ngừng xuất bản…' : 'Ngừng xuất bản'}
          </button>
        </div>
      )}

      {confirmationOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="approval-confirmation-title"
          className="m-4 rounded-2xl border border-emerald-300 bg-white p-5 shadow-lg sm:m-6"
        >
          <h3 id="approval-confirmation-title" className="font-bold text-slate-900">
            Xác nhận duyệt phiên bản
          </h3>
          <p className="mt-3 text-sm leading-6 text-slate-700">
            Bạn xác nhận đã kiểm tra nội dung và nguồn của phiên bản này?
          </p>
          <p className="mt-2 text-sm font-medium leading-6 text-amber-800">
            Sau khi duyệt, phiên bản này sẽ được khóa chỉnh sửa. Nội dung CHƯA được xuất bản cho phụ huynh.
          </p>
          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => setConfirmationOpen(false)}
              className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Hủy
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmationOpen(false);
                onApprove();
              }}
              className="rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800"
            >
              Xác nhận duyệt
            </button>
          </div>
        </div>
      )}


      {publishConfirmationOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="publication-confirmation-title"
          className="m-4 rounded-2xl border border-blue-300 bg-white p-5 shadow-lg sm:m-6"
        >
          <h3 id="publication-confirmation-title" className="font-bold text-slate-900">
            Xác nhận xuất bản phiên bản
          </h3>
          <p className="mt-3 text-sm leading-6 text-slate-700">
            Bạn xác nhận xuất bản phiên bản này?
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-700">
            Phiên bản này sẽ trở thành bản kiến thức chính thức được phép sử dụng cho phần phụ huynh.
          </p>
          <p className="mt-2 text-sm font-medium leading-6 text-emerald-800">
            Nội dung đã duyệt sẽ không bị thay đổi.
          </p>
          {replacesCurrent && (
            <p className="mt-2 text-sm font-medium leading-6 text-amber-800">
              Phiên bản đang xuất bản hiện tại sẽ được thay thế bởi phiên bản này. Phiên bản cũ vẫn được giữ trong lịch sử.
            </p>
          )}
          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => setPublishConfirmationOpen(false)}
              className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Hủy
            </button>
            <button
              type="button"
              onClick={() => {
                setPublishConfirmationOpen(false);
                onPublish();
              }}
              className="rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800"
            >
              Xác nhận xuất bản
            </button>
          </div>
        </div>
      )}


      {unpublishConfirmationOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="unpublication-confirmation-title"
          className="m-4 rounded-2xl border border-rose-300 bg-white p-5 shadow-lg sm:m-6"
        >
          <h3 id="unpublication-confirmation-title" className="font-bold text-slate-900">
            Xác nhận ngừng xuất bản phiên bản
          </h3>
          <p className="mt-3 text-sm leading-6 text-slate-700">
            Bạn xác nhận ngừng xuất bản phiên bản này?
          </p>
          <p className="mt-2 text-sm font-medium leading-6 text-rose-800">
            Phụ huynh sẽ không còn thấy phần giải thích y khoa này.
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-700">
            Phiên bản vẫn được giữ ở trạng thái Đã duyệt và không bị xóa.
          </p>
          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => setUnpublishConfirmationOpen(false)}
              className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Hủy
            </button>
            <button
              type="button"
              onClick={() => {
                setUnpublishConfirmationOpen(false);
                onUnpublish();
              }}
              className="rounded-xl bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-800"
            >
              Xác nhận ngừng xuất bản
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
