import { createElement, useCallback, useEffect, useMemo, type ReactNode } from 'react';
import i18next from 'i18next';
import { I18nextProvider, initReactI18next, useTranslation } from 'react-i18next';
import { loadPreferences, savePreferences } from './preferences';
import {
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  resources,
  supportedLanguages,
} from '@/i18n/resources';
import type { SupportedLanguage } from '@/i18n/types';

export type Lang = SupportedLanguage;

const initialLanguage = isSupportedLanguage(loadPreferences().language)
  ? loadPreferences().language
  : DEFAULT_LANGUAGE;

if (!i18next.isInitialized) {
  void i18next.use(initReactI18next).init({
    resources,
    lng: initialLanguage,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: supportedLanguages,
    defaultNS: 'translation',
    ns: ['translation'],
    interpolation: {
      escapeValue: false,
    },
    returnNull: false,
    missingKeyHandler: (_lngs, _ns, key) => {
      if (import.meta.env.DEV) {
        console.warn(`[i18n] Missing translation key: ${key}`);
      }
    },
  });
}

interface I18nContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string) => string;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = i18next.language;
  }, []);

  useEffect(() => {
    const onLanguageChanged = (lang: string) => {
      document.documentElement.lang = lang;
    };

    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'sd_preferences') return;
      const next = loadPreferences().language;
      if (isSupportedLanguage(next) && i18next.language !== next) {
        void i18next.changeLanguage(next);
      }
    };

    i18next.on('languageChanged', onLanguageChanged);
    window.addEventListener('storage', onStorage);
    return () => {
      i18next.off('languageChanged', onLanguageChanged);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  return createElement(I18nextProvider, { i18n: i18next }, children);
}

export function useI18n(): I18nContextValue {
  const { i18n, t } = useTranslation();
  const lang = isSupportedLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;

  const setLang = useCallback((nextLang: Lang) => {
    const prefs = loadPreferences();
    savePreferences({ ...prefs, language: nextLang });
    void i18n.changeLanguage(nextLang);
  }, [i18n]);

  const translate = useCallback((key: string) => t(key), [t]);

  return useMemo(
    () => ({
      lang,
      setLang,
      t: translate,
    }),
    [lang, setLang, translate],
  );
}

export function useT(): (key: string) => string {
  return useI18n().t;
}
