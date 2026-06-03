import { createRoot } from 'react-dom/client';
import App from './app/App.tsx';
import './styles/index.css';
import { initTheme } from './lib/theme';
import { I18nProvider } from './lib/i18n';

// Áp dụng chủ đề trước khi render để tránh nháy màu.
initTheme();

createRoot(document.getElementById('root')!).render(
  <I18nProvider>
    <App />
  </I18nProvider>,
);
