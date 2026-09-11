import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  regenerateAutoMedicalKnowledge,
  setAutoMedicalKnowledgeTopicVisibility,
} from './medicalKnowledgeApi';

afterEach(() => vi.unstubAllGlobals());

describe('Auto Medical Knowledge regenerate API', () => {
  it('sends only the exact canonical selector when given a revision-like object', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        job_id: 12,
        created: true,
        outcome: 'CREATED',
        job_status: 'QUEUED',
        message: 'Đã tạo yêu cầu mới.',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await regenerateAutoMedicalKnowledge('41', {
      factor_type: 'WEATHER',
      factor_key: 'temperature',
      factor_value: null,
      weather_factor: 'temperature',
      id: 99,
      generation_status: 'INSUFFICIENT',
      sources: [],
    } as never);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init.body))).toEqual({
      disease_group_id: '41',
      factor_type: 'WEATHER',
      factor_key: 'temperature',
      factor_value: null,
      weather_factor: 'temperature',
    });
  });
});

describe('Auto Medical Knowledge topic visibility API', () => {
  it('sends one strict canonical-selector request without revision fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, topic_id: 2, message: 'ok' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await setAutoMedicalKnowledgeTopicVisibility('5', {
      factor_type: 'WEATHER',
      factor_key: 'precipitation',
      factor_value: null,
      weather_factor: 'precipitation',
      id: 8,
      sources: [{ secret: 'must-not-be-sent' }],
    } as never, true);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/medical-knowledge/auto/topics/visibility');
    expect(JSON.parse(String(init.body))).toEqual({
      disease_group_id: '5',
      factor_type: 'WEATHER',
      factor_key: 'precipitation',
      factor_value: null,
      weather_factor: 'precipitation',
      hidden: true,
    });
  });
});
