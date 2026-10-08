import { useEffect, useState } from 'react';
import type { WeatherAIPredictResponse } from '@/lib/api';
import { ParentDiseaseCard, type ParentDiseaseCardRow } from './ParentDiseaseCard';

export function ParentResultNavigator({ rows, result }: {
  rows: ParentDiseaseCardRow[];
  result: WeatherAIPredictResponse;
}) {
  const [index, setIndex] = useState(0);
  // New predictions start at the first group. A late reference response keeps the selection.
  useEffect(() => setIndex(0), [result]);
  const currentIndex = Math.min(index, Math.max(0, rows.length - 1));
  const row = rows[currentIndex];
  if (!row) return null;
  const buttonStyle = 'min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="space-y-4">
      <nav aria-label="Điều hướng nhóm bệnh" className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" className={buttonStyle} disabled={currentIndex === 0} onClick={() => setIndex(currentIndex - 1)} aria-controls="parent-current-disease">
          Nhóm trước
        </button>
        <p role="status" aria-live="polite" aria-atomic="true" className="text-sm font-medium tabular-nums text-slate-600">
          Nhóm {currentIndex + 1} / {rows.length}
        </p>
        <button type="button" className={buttonStyle} disabled={currentIndex === rows.length - 1} onClick={() => setIndex(currentIndex + 1)} aria-controls="parent-current-disease">
          Nhóm tiếp theo
        </button>
      </nav>
      <div id="parent-current-disease">
        <ParentDiseaseCard key={row.disease_id} row={row} featured={currentIndex === 0} anchorDate={result.context.anchor_date} />
      </div>
    </div>
  );
}
