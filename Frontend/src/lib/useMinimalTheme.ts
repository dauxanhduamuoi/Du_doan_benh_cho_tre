import { useEffect, useState } from 'react';

function isMinimalThemeActive(): boolean {
  return document.documentElement.dataset.theme === 'developer';
}

export function useMinimalTheme(): boolean {
  const [isMinimal, setIsMinimal] = useState(isMinimalThemeActive);

  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setIsMinimal(isMinimalThemeActive()));
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  return isMinimal;
}
