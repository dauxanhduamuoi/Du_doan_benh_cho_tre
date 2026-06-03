import { splitDiseaseLabel, getCachedBilingual, type DiseaseLabel } from '@/lib/disease';

interface Props {
  raw: string | null | undefined;
  className?: string;
  /** Override map nếu caller đã có sẵn (tránh re-lookup). */
  map?: Record<string, string>;
  /** Tự động cắt ngắn để fit cột hẹp. */
  truncate?: boolean;
}

/**
 * Hiển thị tên bệnh 2 dòng: tiếng Việt (dòng trên) + tiếng Anh (dòng dưới).
 */
export default function DiseaseLabelCell({ raw, className, map, truncate }: Props) {
  const dict = map ?? getCachedBilingual();
  const label: DiseaseLabel = splitDiseaseLabel(raw, dict);

  return (
    <div className={className}>
      <div className={`text-slate-800 ${truncate ? 'truncate' : ''}`} title={label.vi}>
        {label.vi || '—'}
      </div>
      {label.en && (
        <div
          className={`text-[11px] text-slate-400 italic mt-0.5 ${truncate ? 'truncate' : ''}`}
          title={label.en}
        >
          {label.en}
        </div>
      )}
    </div>
  );
}
