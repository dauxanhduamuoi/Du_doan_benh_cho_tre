import en from './locales/en';
import vi from './locales/vi';
import type { LocaleMessages, SupportedLanguage } from './types';

export type { SupportedLanguage } from './types';

export const DEFAULT_LANGUAGE: SupportedLanguage = 'vi';

export const resources: Record<SupportedLanguage, { translation: LocaleMessages }> = {
  vi: { translation: vi },
  en: { translation: en },
};

export const supportedLanguages = Object.keys(resources) as SupportedLanguage[];

export const languageOptions: Array<{ code: SupportedLanguage; label: string }> = [
  { code: 'vi', label: 'Tiếng Việt' },
  { code: 'en', label: 'English' },
];

export function isSupportedLanguage(value: unknown): value is SupportedLanguage {
  return typeof value === 'string' && supportedLanguages.includes(value as SupportedLanguage);
}
