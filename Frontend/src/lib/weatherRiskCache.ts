import type * as api from './api';

export type WeatherRiskLocationMode = 'geo' | 'manual';

export interface CachedWeatherRiskProvince extends api.AreaOption {
  latitude: number;
  longitude: number;
}

export interface CachedWeatherRiskState {
  result: api.WeatherAIPredictResponse;
  locationMode: WeatherRiskLocationMode;
  provinceCode: string;
  geoPoint: {
    latitude: number;
    longitude: number;
    province: CachedWeatherRiskProvince | null;
  } | null;
  geoStatus: string;
  ageGroup: string;
  gender: string;
  topKInput: string;
  pageSizeInput: string;
  riskPage: number;
  savedAt: string;
}

const STORAGE_KEY = 'sd_weather_ai_result';

export function loadWeatherRiskCache(): CachedWeatherRiskState | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as Partial<CachedWeatherRiskState>;
    if (!parsed.result || !parsed.ageGroup || !parsed.gender) return null;

    return {
      result: parsed.result,
      locationMode: parsed.locationMode === 'geo' ? 'geo' : 'manual',
      provinceCode: parsed.provinceCode ?? '',
      geoPoint: parsed.geoPoint ?? null,
      geoStatus: parsed.geoStatus ?? 'Chua lay vi tri hien tai.',
      ageGroup: parsed.ageGroup,
      gender: parsed.gender,
      topKInput: parsed.topKInput ?? '10',
      pageSizeInput: parsed.pageSizeInput ?? '5',
      riskPage: Number.isFinite(parsed.riskPage) ? Number(parsed.riskPage) : 1,
      savedAt: parsed.savedAt ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export function saveWeatherRiskCache(state: CachedWeatherRiskState) {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Cache is only a convenience layer; prediction itself should keep working.
  }
}

export function clearWeatherRiskCache() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(STORAGE_KEY);
}
