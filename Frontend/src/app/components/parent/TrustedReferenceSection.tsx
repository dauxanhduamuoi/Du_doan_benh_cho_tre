import type { TrustedReferenceItem } from '@/lib/api';
import { safeTrustedReferenceUrl } from '../weather-ai/trustedReferences';

export function TrustedReferenceSection({ items, collapsible = false }: { items: TrustedReferenceItem[]; collapsible?: boolean }) {
  const seen = new Set<number>();
  const sources = items.flatMap((item) => item.references).filter((source) => {
    if (seen.has(source.source_id)) return false;
    seen.add(source.source_id);
    return true;
  });
  if (sources.length === 0) return null;
  const bibliography = (
    <ul className="mt-3 divide-y divide-slate-200">
      {sources.map((source) => {
        const url = safeTrustedReferenceUrl(source.original_url);
        const metadata = [source.journal, source.publication_year, source.provider_id || source.source_type]
          .filter((value) => value !== null && value !== '');
        return (
          <li key={source.source_id} className="py-3 first:pt-0 last:pb-0">
            <h5 className="min-w-0 [overflow-wrap:anywhere] text-sm font-medium leading-6 text-slate-800">{source.title}</h5>
            <p className="mt-1 [overflow-wrap:anywhere] text-sm leading-6 text-slate-500">{metadata.join(' · ')}</p>
            {url && <a href={url} target="_blank" rel="noopener noreferrer" aria-label={`Xem nguồn gốc: ${source.title}`} className="mt-1 inline-block py-2 text-sm font-medium text-teal-800 underline underline-offset-4 hover:text-teal-950">Xem nguồn gốc</a>}
          </li>
        );
      })}
    </ul>
  );
  return (
    <section aria-label="Nguồn tham khảo" className="border-t border-slate-200 pt-5">
      <h4 className="text-sm font-semibold text-slate-900">Nguồn tham khảo</h4>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        Các tài liệu này dùng để đọc thêm và không quyết định kết quả xếp hạng của mô hình.
      </p>
      {collapsible ? (
        <details className="mt-2">
          <summary className="cursor-pointer rounded-md py-2 text-sm font-medium text-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700">
            Xem tài liệu tham khảo ({sources.length})
          </summary>
          {bibliography}
        </details>
      ) : bibliography}
    </section>
  );
}
