import type { TrustedReferenceItem, TrustedReferenceSelector, WeatherAIPredictResponse } from '@/lib/api';
import { buildPublishedMedicalKnowledgeSelectors } from './publishedMedicalKnowledge';

export function buildTrustedReferenceSelectors(response: WeatherAIPredictResponse): TrustedReferenceSelector[] {
  return buildPublishedMedicalKnowledgeSelectors(response).map((selector) => ({
    disease_group_id: selector.disease_group_id,
    factor_type: selector.factor_type,
    factor_key: selector.factor_key,
    factor_value: selector.factor_value,
  }));
}

export function trustedReferenceSelectorKey(selector: TrustedReferenceSelector): string {
  return JSON.stringify([selector.disease_group_id, selector.factor_type, selector.factor_key, selector.factor_value]);
}

export function matchTrustedReferenceItems(
  items: TrustedReferenceItem[], selectors: TrustedReferenceSelector[],
): TrustedReferenceItem[] {
  const requested = new Set(selectors.map(trustedReferenceSelectorKey));
  return items.filter((item) => requested.has(trustedReferenceSelectorKey(item.selector)));
}

export function safeTrustedReferenceUrl(value: string): string | null {
  const url = value.trim();
  if (!/^https:\/\//i.test(url) || /\s/.test(url)) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && parsed.hostname && !parsed.username && !parsed.password ? url : null;
  } catch {
    return null;
  }
}
