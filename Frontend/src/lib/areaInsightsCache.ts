import type * as api from './api';
import type { ProvinceRegionRecord } from './provinceRegions';

export type CachedAreaRegionFilter = 'all' | ProvinceRegionRecord['mien_code'];

export interface CachedAreaInsightsState {
  provinces: api.AreaOption[];
  provinceRegions: ProvinceRegionRecord[];
  regionFilter: CachedAreaRegionFilter;
  provinceCodes: string[];
  caseSummary: api.AreaCaseSummary[];
  diseaseSummary: api.AreaDiseaseSummary[];
  localRisks: api.AreaLocalRisk[];
  diseasePage: number;
  diseasePageSize: number;
  riskPage: number;
  riskPageSize: number;
  recommendations: string[];
  savedAt: string;
}

const STORAGE_KEY = 'sd_area_insights_state';

function normalizePage(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function loadAreaInsightsCache(): CachedAreaInsightsState | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as Partial<CachedAreaInsightsState>;
    return {
      provinces: Array.isArray(parsed.provinces) ? parsed.provinces : [],
      provinceRegions: Array.isArray(parsed.provinceRegions) ? parsed.provinceRegions : [],
      regionFilter:
        parsed.regionFilter === 'north' || parsed.regionFilter === 'central' || parsed.regionFilter === 'south'
          ? parsed.regionFilter
          : 'all',
      provinceCodes: Array.isArray(parsed.provinceCodes) ? parsed.provinceCodes.map(String) : [],
      caseSummary: Array.isArray(parsed.caseSummary) ? parsed.caseSummary : [],
      diseaseSummary: Array.isArray(parsed.diseaseSummary) ? parsed.diseaseSummary : [],
      localRisks: Array.isArray(parsed.localRisks) ? parsed.localRisks : [],
      diseasePage: normalizePage(parsed.diseasePage, 1),
      diseasePageSize: normalizePage(parsed.diseasePageSize, 10),
      riskPage: normalizePage(parsed.riskPage, 1),
      riskPageSize: normalizePage(parsed.riskPageSize, 10),
      recommendations: Array.isArray(parsed.recommendations) ? parsed.recommendations.map(String) : [],
      savedAt: parsed.savedAt ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export function saveAreaInsightsCache(state: CachedAreaInsightsState) {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Cache only improves navigation UX; data can still be loaded from the API.
  }
}

export function clearAreaInsightsCache() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(STORAGE_KEY);
}
