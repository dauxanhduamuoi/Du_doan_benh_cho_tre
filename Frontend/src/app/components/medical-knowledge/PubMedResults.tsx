import { Loader2, Save } from 'lucide-react';
import type { PubMedSearchResponse } from '@/lib/medicalKnowledgeApi';
import PubMedResultCard from './PubMedResultCard';

interface Props {
  response: PubMedSearchResponse;
  selectedPmids: Set<string>;
  importedPmids: Set<string>;
  importing: boolean;
  onToggle: (pmid: string) => void;
  onToggleAll: () => void;
  onImport: () => void;
}

export default function PubMedResults(props: Props) {
  if (props.response.results.length === 0) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
        <h2 className="font-bold text-slate-800">Không tìm thấy tài liệu phù hợp</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Không tìm thấy tài liệu phù hợp với từ khóa hiện tại. Bạn có thể điều chỉnh từ khóa và tìm lại.
        </p>
      </div>
    );
  }

  const allSelected = props.response.results.every((paper) => props.selectedPmids.has(paper.pmid));
  const selectedCount = props.selectedPmids.size;

  return (
    <section aria-labelledby="pubmed-results-title">
      <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 id="pubmed-results-title" className="text-lg font-bold text-slate-900">
              Tìm thấy {props.response.count} tài liệu
            </h2>
            <p className="mt-1 text-sm text-slate-500">Đã chọn {selectedCount} tài liệu</p>
          </div>
          <button
            type="button"
            onClick={props.onToggleAll}
            className="self-start rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 sm:self-auto"
          >
            {allSelected ? 'Bỏ chọn tất cả' : 'Chọn tất cả kết quả'}
          </button>
        </div>
        <details className="mt-4 rounded-xl bg-slate-50 px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-600">Chi tiết tìm kiếm</summary>
          <code className="mt-2 block whitespace-pre-wrap break-words text-xs leading-5 text-slate-600">{props.response.query}</code>
        </details>
      </div>

      <div className="space-y-4">
        {props.response.results.map((paper) => (
          <PubMedResultCard
            key={paper.pmid}
            paper={paper}
            selected={props.selectedPmids.has(paper.pmid)}
            imported={props.importedPmids.has(paper.pmid)}
            onToggle={() => props.onToggle(paper.pmid)}
          />
        ))}
      </div>

      <div className="sticky bottom-3 z-10 mt-5 rounded-2xl border border-blue-200 bg-white/95 p-3 shadow-lg backdrop-blur sm:flex sm:items-center sm:justify-between sm:p-4">
        <p className="mb-3 text-sm font-semibold text-slate-700 sm:mb-0">Đã chọn {selectedCount} tài liệu</p>
        <button
          type="button"
          onClick={props.onImport}
          disabled={selectedCount === 0 || props.importing}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300 sm:w-auto"
        >
          {props.importing ? <Loader2 size={17} className="animate-spin" /> : <Save size={17} />}
          {props.importing
            ? 'Đang thêm vào kho…'
            : `Thêm ${selectedCount} tài liệu vào kho nguồn`}
        </button>
      </div>
    </section>
  );
}
