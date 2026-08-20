import { useEffect, useState, type FormEvent } from 'react';
import { BookOpen, Save } from 'lucide-react';
import type {
  DraftRevision,
  DraftRevisionPatch,
  EvidenceLevel,
  EvidenceScope,
} from '@/lib/medicalKnowledgeApi';

interface Props {
  revision: DraftRevision;
  saving: boolean;
  onSave: (payload: DraftRevisionPatch) => void;
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

export default function MedicalDraftReviewForm({ revision, saving, onSave }: Props) {
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
  }, [revision]);

  const editable = revision.status === 'DRAFT';
  const canSave = editable && !saving && Boolean(
    form.short_explanation_vi.trim() &&
      form.detailed_explanation_vi.trim() &&
      form.limitations_vi.trim(),
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSave) onSave(form);
  }

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
          <span className={`rounded-full px-3 py-1 text-xs font-bold ${
            revision.status === 'DRAFT'
              ? 'bg-amber-100 text-amber-800'
              : 'bg-slate-200 text-slate-700'
          }`}>
            {revision.status}{revision.status === 'DRAFT' ? ' — Chưa xuất bản' : ' — Chỉ đọc'}
          </span>
        </div>
        <dl className="mt-4 grid gap-2 text-sm text-slate-700 sm:grid-cols-3">
          <div><dt className="font-semibold">Nhóm bệnh</dt><dd>{revision.disease_group_name}</dd></div>
          <div><dt className="font-semibold">Yếu tố thời tiết</dt><dd>{revision.weather_factor}</dd></div>
          <div><dt className="font-semibold">Nguồn đã sử dụng</dt><dd>{revision.sources.length} tài liệu PubMed</dd></div>
        </dl>
      </div>

      <div className="m-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900 sm:m-6">
        Bản nháp được AI tạo từ thông tin và tóm tắt PubMed của các nguồn đã chọn. Nhân viên y tế cần kiểm tra nội dung và nguồn trước khi duyệt ở bước tiếp theo.
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
                {source.relevance_note && <p className="mt-2 leading-6 text-blue-800">{source.relevance_note}</p>}
              </article>
            ))}
          </div>
        </div>

        {editable && (
          <button
            type="submit"
            disabled={!canSave}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 px-5 py-3 text-sm font-bold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            <Save size={17} /> {saving ? 'Đang lưu bản nháp…' : 'Lưu bản nháp'}
          </button>
        )}
      </form>
    </section>
  );
}
