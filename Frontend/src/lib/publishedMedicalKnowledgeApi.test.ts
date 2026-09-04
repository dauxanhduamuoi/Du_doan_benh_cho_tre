import { afterEach, describe, expect, it, vi } from 'vitest';
import { getPublicPublishedMedicalKnowledge } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('published Medical Knowledge API sanitizer', () => {
  it('fails a malformed public payload closed without throwing', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: [{
          disease_group_id: '17',
          weather_factor: 'precipitation',
          revision_id: 1,
          evidence_level: 'SUPPORTED',
          evidence_scope: 'WHOLE_GROUP',
          short_explanation_vi: 'Looks valid',
          detailed_explanation_vi: null,
          limitations_vi: 'Missing details makes the entire row unsafe',
          sources: [],
          raw_evidence_text: 'must not be consumed',
        }],
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(getPublicPublishedMedicalKnowledge([
      {
        disease_group_id: '17',
        factor_type: 'WEATHER',
        factor_key: 'precipitation',
        factor_value: null,
        weather_factor: 'precipitation',
      },
    ])).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/public/medical-knowledge/published',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
