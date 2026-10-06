import type { TrustedReferenceItem } from '@/lib/api';
import { safeTrustedReferenceUrl } from '../weather-ai/trustedReferences';

export function TrustedReferenceSection({ items }: { items: TrustedReferenceItem[] }) {
  const seen = new Set<number>();
  const sources = items.flatMap((item) => item.references).filter((source) => {
    if (seen.has(source.source_id)) return false;
    seen.add(source.source_id);
    return true;
  });
  if (sources.length === 0) return null;
  return (
    <section aria-label="Tài liệu tham khảo" className="rounded-2xl border border-sky-100 bg-sky-50/50 p-4">
      <h4 className="text-sm font-extrabold text-sky-950">Tài liệu tham khảo</h4>
      <p className="mt-1 text-xs leading-5 text-slate-600">
        Các tài liệu này dùng để đọc thêm và không quyết định kết quả xếp hạng của mô hình.
      </p>
      <ul className="mt-3 space-y-2">
        {sources.map((source) => {
          const url = safeTrustedReferenceUrl(source.original_url);
          const metadata = [source.journal, source.publication_year, source.provider_id || source.source_type]
            .filter((value) => value !== null && value !== '');
          return (
            <li key={source.source_id} className="rounded-xl border border-sky-100 bg-white p-3">
              <h5 className="text-sm font-bold leading-5 text-slate-800">{source.title}</h5>
              <p className="mt-1 text-xs text-slate-500">{metadata.join(' · ')}</p>
              {url && <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs font-bold text-sky-700 underline">Đọc nguồn gốc</a>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
