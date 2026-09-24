import { BookMarked, Loader2 } from 'lucide-react';
import {
  isTopicSourceAiReadable,
  MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES,
  evidenceContentLabel,
  type TopicSourceLibrary,
} from '@/lib/medicalKnowledgeApi';

interface Props {
  diseaseName: string;
  factorLabel: string;
  library: TopicSourceLibrary | null;
  loading: boolean;
  selectedSourceIds: Set<number>;
  onToggle: (sourceId: number) => void;
  onSelectAllUsable: () => void;
  selectionNotice: string | null;
}

export default function MedicalTopicSourceLibrary(props: Props) {
  if (!props.factorLabel) return null;
  const usableSources = props.library?.sources.filter(isTopicSourceAiReadable) ?? [];
  const selectedCount = usableSources.filter((source) => props.selectedSourceIds.has(source.source_id)).length;
  const maxReached = selectedCount >= MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES;

  return (
    <section aria-labelledby="topic-source-library-heading" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <h2 id="topic-source-library-heading" className="flex items-center gap-2 text-lg font-bold text-slate-900">
        <BookMarked size={20} /> Kho nguồn của chủ đề
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        {props.diseaseName} — {props.factorLabel}
      </p>
      <p className="mt-2 text-sm leading-6 text-slate-500">
        Kho này lưu các tài liệu bạn đã thu thập cho nhóm bệnh và yếu tố hiện tại.
        Chọn từng nguồn bên dưới nếu muốn AI dùng cho bản nháp tiếp theo.
      </p>

      {props.loading ? (
        <p role="status" className="mt-4 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={16} className="animate-spin" /> Đang tải kho nguồn…
        </p>
      ) : props.library && props.library.sources.length > 0 ? (
        <div className="mt-4 space-y-3">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <div>
              <p className="text-sm font-semibold text-slate-700">{props.library.sources.length} tài liệu đã lưu</p>
              <p className="mt-1 text-sm font-semibold text-violet-800">
                {selectedCount} / {MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES} nguồn đã chọn
              </p>
            </div>
            <button
              type="button"
              onClick={props.onSelectAllUsable}
              disabled={usableSources.length === 0}
              className="rounded-lg border border-violet-300 px-3 py-2 text-sm font-semibold text-violet-800 hover:bg-violet-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Chọn tất cả nguồn AI đọc được
            </button>
          </div>
          {usableSources.length > MEDICAL_KNOWLEDGE_MAX_DRAFT_SOURCES && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Có {usableSources.length} nguồn AI đọc được. Bạn có thể chọn tối đa 10 nguồn cho một bản nháp.
            </p>
          )}
          {(maxReached || props.selectionNotice) && (
            <p role="status" className="rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-900">
              {props.selectionNotice ?? 'Một bản nháp hiện hỗ trợ tối đa 10 nguồn.'}
            </p>
          )}
          {props.library.sources.map((source) => (
            <label key={source.source_id} className={`flex items-start gap-3 rounded-xl border p-3 ${isTopicSourceAiReadable(source) ? 'cursor-pointer border-slate-200 hover:border-violet-300 hover:bg-violet-50/40' : 'cursor-not-allowed border-slate-200 bg-slate-50'}`}>
              <input
                type="checkbox"
                checked={props.selectedSourceIds.has(source.source_id)}
                onChange={() => props.onToggle(source.source_id)}
                disabled={!isTopicSourceAiReadable(source) || (maxReached && !props.selectedSourceIds.has(source.source_id))}
                aria-label={`Chọn nguồn ${source.title} cho bản nháp`}
                className="mt-1 size-5 shrink-0 rounded border-slate-300 text-violet-700 focus:ring-violet-500"
              />
              <span className="min-w-0">
                <span className="block font-semibold text-slate-900">{source.title}</span>
                <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span className="font-bold">{source.provider_id ?? 'PUBMED'}</span>
                  {source.pmid && <span>PMID: {source.pmid}</span>}
                  {source.pmcid && <span>PMCID: {source.pmcid}</span>}
                  {source.publication_year && <span>Năm {source.publication_year}</span>}
                  {source.journal && <span>{source.journal}</span>}
                </span>
                <span className="mt-2 inline-flex rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-800">
                  {evidenceContentLabel(source.content_kind)}
                </span>
                {!isTopicSourceAiReadable(source) && (
                  <span className="mt-2 block text-xs text-slate-600">
                    <span className="block">Nguồn vẫn được lưu trong kho để tham khảo.</span>
                    <span className="mt-1 block font-medium">Đã lưu để tham khảo · không thể chọn cho AI Draft.</span>
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
      ) : (
        <p className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500">
          Chưa có tài liệu trong kho chủ đề. Hãy tìm trong các nguồn được bật và thêm tài liệu phù hợp.
        </p>
      )}
    </section>
  );
}
