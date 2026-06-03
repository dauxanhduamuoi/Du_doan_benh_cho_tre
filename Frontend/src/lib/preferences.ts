import {
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  type SupportedLanguage,
} from '@/i18n/resources';

// Quản lý tuỳ chọn UI lưu trong localStorage.

export interface UserPreferences {
  theme: 'light' | 'dark' | 'system' | 'multicolor';
  language: SupportedLanguage;
  notifyHighRisk: boolean;
  notifyImport: boolean;
  notifyForecast: boolean;
}

const KEY = 'sd_preferences';

export const defaultPreferences: UserPreferences = {
  theme: 'light',
  language: DEFAULT_LANGUAGE,
  notifyHighRisk: true,
  notifyImport: true,
  notifyForecast: true,
};

export function loadPreferences(): UserPreferences {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...defaultPreferences };
    const parsed = JSON.parse(raw) as Partial<UserPreferences>;
    const language = isSupportedLanguage(parsed.language) ? parsed.language : DEFAULT_LANGUAGE;
    const theme =
      parsed.theme === 'dark' || parsed.theme === 'system' || parsed.theme === 'light' || parsed.theme === 'multicolor'
        ? parsed.theme
        : defaultPreferences.theme;
    return { ...defaultPreferences, ...parsed, theme, language };
  } catch {
    return { ...defaultPreferences };
  }
}

export function savePreferences(prefs: UserPreferences) {
  localStorage.setItem(KEY, JSON.stringify(prefs));
}
