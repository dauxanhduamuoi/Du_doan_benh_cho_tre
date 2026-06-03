# Frontend i18n

The app uses `i18next` + `react-i18next`.

## Add a new language

1. Create a locale file in `src/i18n/locales`, for example `fr.ts`.
2. Export all translation keys as a `LocaleMessages` object.
3. Add the language code to `SupportedLanguage` in `src/i18n/types.ts`.
4. Register the file in `src/i18n/resources.ts` and add it to `languageOptions`.

Components should use `useT()` or `useI18n()` from `@/lib/i18n`. This keeps the app code independent from the concrete i18n library.
