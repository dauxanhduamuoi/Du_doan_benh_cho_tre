import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getPublicTrustedReferences, type TrustedReferenceSelector } from './api';

const selector: TrustedReferenceSelector = {
  disease_group_id: '17', factor_type: 'WEATHER', factor_key: 'precipitation', factor_value: null,
};
const reference = {
  source_id: 12, provider_id: 'WHO', external_id: 'persisted-id', source_type: 'WHO', source_kind: 'HEALTH_GUIDANCE',
  title: 'Stored source title', journal: 'Stored publisher', publication_year: 2025, original_url: 'https://example.org/source',
};
function mockPayload(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe('Trusted References metadata API', () => {
  it('accepts reference-only payload and strips all generated/internal fields', async () => {
    localStorage.setItem('sd_token', 'SHOULD_NOT_SEND');
    const fetchMock = mockPayload({ items: [{
      selector: { ...selector, weather_factor: 'precipitation', generated: 'PRIVATE' },
      references: [{ ...reference, short_explanation_vi: 'DO NOT RETURN', raw_metadata_json: { private: true } }],
      detailed_explanation_vi: 'DO NOT RETURN',
    }] });
    await expect(getPublicTrustedReferences([selector])).resolves.toEqual({ items: [{ selector, references: [reference] }] });
    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe('/api/public/trusted-references');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ items: [selector] });
    expect(options.headers).not.toHaveProperty('Authorization');
  });

  it('accepts empty references and nullable persisted metadata', async () => {
    mockPayload({ items: [{ selector, references: [] }, { selector, references: [{
      ...reference, provider_id: null, external_id: null, source_kind: null, journal: null, publication_year: null,
    }] }] });
    const result = await getPublicTrustedReferences([selector]);
    expect(result.items[0].references).toEqual([]);
    expect(result.items[1].references[0].provider_id).toBeNull();
  });

  it.each([null, [], {}, { items: null }, { items: [null] }, { items: [{ selector, references: null }] }])(
    'fails malformed payload closed: %j', async (payload) => {
      mockPayload(payload);
      await expect(getPublicTrustedReferences([selector])).resolves.toEqual({ items: [] });
    },
  );

  it.each([
    { ...selector, factor_value: '42' }, { ...selector, factor_key: 'unknown' },
    { ...selector, disease_group_id: 'wrong' }, { ...selector, factor_value: undefined },
    { ...selector, factor_type: 'AGE', factor_key: 'age_group', factor_value: null },
    { ...selector, factor_type: 'SEX', factor_key: 'gender', factor_value: '' },
  ])('rejects malformed selector identity: %j', async (invalid) => {
    mockPayload({ items: [{ selector: invalid, references: [reference] }] });
    await expect(getPublicTrustedReferences([selector])).resolves.toEqual({ items: [] });
  });

  it.each([{ source_id: 0 }, { title: '' }, { publication_year: 9999 }, { original_url: null }, { provider_id: {} }])(
    'skips invalid source metadata: %j', async (invalid) => {
      mockPayload({ items: [{ selector, references: [{ ...reference, ...invalid }] }] });
      expect((await getPublicTrustedReferences([selector])).items[0].references).toEqual([]);
    },
  );

  it('preserves source order from the API', async () => {
    mockPayload({ items: [{ selector, references: [reference, { ...reference, source_id: 3, title: 'Second' }] }] });
    expect((await getPublicTrustedReferences([selector])).items[0].references.map((source) => source.source_id)).toEqual([12, 3]);
  });

  it('splits larger prediction batches at the backend bound of 100', async () => {
    const fetchMock = mockPayload({ items: [] });
    await getPublicTrustedReferences(Array.from({ length: 101 }, (_, index) => ({ ...selector, disease_group_id: String(index) })));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([, options]) => JSON.parse(options.body).items.length)).toEqual([100, 1]);
  });

  it('does not make a request for an empty selector list', async () => {
    const fetchMock = mockPayload({ items: [] });
    await expect(getPublicTrustedReferences([])).resolves.toEqual({ items: [] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('propagates HTTP failure for the optional caller to isolate', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'Unavailable' }) }));
    await expect(getPublicTrustedReferences([selector])).rejects.toBeInstanceOf(ApiError);
  });
});
