// Quản lý chủ đề sáng/tối/theo hệ thống.
// Tự áp class `dark` lên <html>, nghe media query khi chọn "system".

import { defaultPreferences, loadPreferences, type UserPreferences } from './preferences';

export type Theme = UserPreferences['theme'];

const PREFERS_DARK = '(prefers-color-scheme: dark)';

function applyClass(theme: Theme, isDark: boolean, multicolorHue: number) {
  const root = document.documentElement;
  if (isDark) root.classList.add('dark');
  else root.classList.remove('dark');
  root.style.setProperty('--mc-hue', String(multicolorHue));
  root.dataset.theme =
    theme === 'multicolor' || theme === 'developer'
      ? theme
      : isDark
        ? 'dark'
        : 'light';
}

function resolveIsDark(theme: Theme): boolean {
  if (theme === 'dark') return true;
  if (theme === 'light' || theme === 'multicolor' || theme === 'developer') return false;
  return window.matchMedia(PREFERS_DARK).matches;
}

let mediaListener: ((e: MediaQueryListEvent) => void) | null = null;

function bindSystemListener(theme: Theme) {
  const mq = window.matchMedia(PREFERS_DARK);

  if (mediaListener) {
    mq.removeEventListener('change', mediaListener);
    mediaListener = null;
  }

  if (theme === 'system') {
    mediaListener = (e: MediaQueryListEvent) =>
      applyClass(theme, e.matches, defaultPreferences.multicolorHue);
    mq.addEventListener('change', mediaListener);
  }
}

export function applyTheme(theme: Theme, multicolorHue = defaultPreferences.multicolorHue) {
  applyClass(theme, resolveIsDark(theme), multicolorHue);
  bindSystemListener(theme);
}

export function initTheme() {
  const prefs = loadPreferences();
  applyTheme(prefs.theme, prefs.multicolorHue);
}
