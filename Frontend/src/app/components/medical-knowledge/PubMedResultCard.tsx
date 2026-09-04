import { useState } from 'react';
import { CheckCircle2, Database, ExternalLink } from 'lucide-react';
import {
  evidenceContentLabel,
  type PubMedPaper,
} from '@/lib/medicalKnowledgeApi';

interface Props {
  paper: PubMedPaper;
  selected: boolean;
  onToggle: () => void;
}

export default function PubMedResultCard({ paper, selected, onToggle }: Props) {
  const [expanded, setExpanded] = useState(false);
  const longAbstract = Boolean(paper.abstract_text && paper.abstract_text.length > 320);
  const abstract = paper.abstract_text && longAbstract && !expanded
    ? `${paper.abstract_text.slice(0, 320).trim()}…`
    : paper.abstract_text;

  return (
    <article className={`rounded-2xl border bg-white p-4 shadow-sm transition sm:p-5 ${selected ? 'border-blue-400 ring-2 ring-blue-100' : 'border-slate-200'}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          disabled={paper.in_topic_library}
          aria-label={`Chọn tài liệu ${paper.title}`}
          className="mt-1.5 size-5 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <h3 className="break-words text-base font-bold leading-6 text-slate-900">{paper.title}</h3>
            {paper.in_topic_library ? (
              <span className="inline-flex shrink-0 items-center gap-1 self-start rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                <CheckCircle2 size={13} /> Đã có trong kho chủ đề
              </span>
            ) : paper.stored_globally ? (
              <span className="inline-flex shrink-0 items-center gap-1 self-start rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">
                <Database size={13} /> Đã lưu trong hệ thống
              </span>
            ) : null}
          </div>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {paper.publication_year && <span>Năm {paper.publication_year}</span>}
            {paper.journal && <span className="break-words">{paper.journal}</span>}
            <span>PMID: {paper.pmid}</span>
            {paper.pmcid && <span>PMCID: {paper.pmcid}</span>}
            {paper.doi && <span className="break-all">DOI: {paper.doi}</span>}
          </div>
          {paper.authors && <p className="mt-2 break-words text-sm text-slate-600">{paper.authors}</p>}

          {paper.content_kind && (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-full bg-violet-100 px-2.5 py-1 font-semibold text-violet-800">
                {evidenceContentLabel(paper.content_kind)}
              </span>
              {paper.pmcid && (
                <span className="font-medium text-slate-600">{paper.pmcid}</span>
              )}
            </div>
          )}

          <div className="mt-4 rounded-xl bg-slate-50 p-3">
            {abstract ? (
              <>
                <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{abstract}</p>
                {longAbstract && (
                  <button
                    type="button"
                    onClick={() => setExpanded((value) => !value)}
                    className="mt-2 text-sm font-semibold text-blue-700 hover:text-blue-800"
                  >
                    {expanded ? 'Thu gọn' : 'Xem tóm tắt đầy đủ'}
                  </button>
                )}
              </>
            ) : (
              <p className="text-sm italic text-slate-500">PubMed không cung cấp tóm tắt cho tài liệu này.</p>
            )}
          </div>

          <a
            href={paper.pubmed_url}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-blue-700 hover:underline"
            aria-label={`Mở tài liệu ${paper.title} trên PubMed trong tab mới`}
          >
            Mở trên PubMed <ExternalLink size={14} />
          </a>
        </div>
      </div>
    </article>
  );
}
