/**
 * Helper sort các nhóm tuổi (BE trả tiếng Việt) theo thứ tự từ nhỏ đến lớn.
 * BE có thể trả label dạng:
 *   - "Dưới 1 tuổi"
 *   - "1-5 tuổi"
 *   - "6-10 tuổi" (hoặc "6-10")
 *   - "11-15 tuổi"
 *   - "Trên 15 tuổi"
 *   - "Không rõ" → đẩy về cuối
 */

const AGE_ORDER: Record<string, number> = {
  'Dưới 1 tuổi': 0,
  '1-5 tuổi': 1,
  '6-10 tuổi': 2,
  '6-10': 2,
  '11-15 tuổi': 3,
  'Trên 15 tuổi': 4,
};

export function ageGroupRank(label: string | null | undefined): number {
  if (!label) return 999;
  const trimmed = label.trim();
  if (trimmed in AGE_ORDER) return AGE_ORDER[trimmed];

  // Heuristic fallback: parse số đầu tiên
  if (/dưới\s*1/i.test(trimmed)) return 0;
  if (/^1[-–]5/.test(trimmed)) return 1;
  if (/^6[-–]10/.test(trimmed)) return 2;
  if (/^11[-–]15/.test(trimmed)) return 3;
  if (/trên\s*15|>\s*15/i.test(trimmed)) return 4;
  return 999;
}

export function sortAgeGroups<T>(rows: T[], getLabel: (row: T) => string | null | undefined): T[] {
  return [...rows].sort((a, b) => ageGroupRank(getLabel(a)) - ageGroupRank(getLabel(b)));
}
