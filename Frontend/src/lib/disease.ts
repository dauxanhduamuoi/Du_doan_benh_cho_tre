/**
 * Trợ giúp hiển thị tên bệnh song ngữ + tách "VN - EN" thành 2 dòng.
 *
 * Backend gộp `disease_group` thường ở dạng "Tiếng Việt - English name". Ta
 * tách ra để FE render dòng trên (VN, in đậm) và dòng dưới (EN, mờ hơn).
 *
 * Nếu không có dấu " - " thì có thể tra qua API `/api/reports/disease-bilingual`
 * (gọi 1 lần, cache trong module) để lấy bản dịch tiếng Anh.
 */

import * as api from './api';

let bilingualCache: Record<string, string> | null = null;
let bilingualPromise: Promise<Record<string, string>> | null = null;

export async function ensureBilingualMap(): Promise<Record<string, string>> {
  if (bilingualCache) return bilingualCache;
  if (!bilingualPromise) {
    bilingualPromise = api
      .getDiseaseBilingual()
      .then((m) => {
        bilingualCache = m;
        return m;
      })
      .catch(() => {
        bilingualCache = {};
        return bilingualCache;
      });
  }
  return bilingualPromise;
}

export function getCachedBilingual(): Record<string, string> {
  return bilingualCache ?? {};
}

export interface DiseaseLabel {
  vi: string;
  en: string | null;
}

/**
 * Tách `disease_group` thành (vi, en).
 * Ưu tiên parse pattern "VN - EN"; nếu không có → tra cache map.
 */
export function splitDiseaseLabel(raw: string | null | undefined, map?: Record<string, string>): DiseaseLabel {
  const text = (raw ?? '').trim();
  if (!text) return { vi: '', en: null };

  // Pattern phổ biến từ dataset: "Tên tiếng Việt - English name"
  const idx = text.indexOf(' - ');
  if (idx > 0) {
    const vi = text.slice(0, idx).trim();
    const en = text.slice(idx + 3).trim();
    return { vi, en: en || null };
  }

  const lookup = (map ?? bilingualCache ?? {})[text];
  return { vi: text, en: lookup || null };
}

/**
 * Tìm kiếm không phân biệt dấu/ký tự hoa, hỗ trợ tách từ.
 * Match nếu MỌI từ trong query đều xuất hiện trong haystack.
 */
export function fuzzyMatch(haystack: string, query: string): boolean {
  if (!query) return true;
  const norm = (s: string) =>
    s
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  const h = norm(haystack);
  return norm(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => h.includes(token));
}
