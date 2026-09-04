import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from './api';

describe('structured Medical Knowledge API errors', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('preserves the domain code and safe message from FastAPI detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: 'DRAFT_SOURCE_NOT_IN_TOPIC',
        message: 'Selected source is outside the exact topic',
      },
    }), {
      status: 422,
      headers: { 'Content-Type': 'application/json' },
    })));

    try {
      await request('/api/medical-knowledge/drafts/generate');
      throw new Error('Expected request to reject');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(422);
      expect((error as ApiError).code).toBe('DRAFT_SOURCE_NOT_IN_TOPIC');
      expect((error as ApiError).detail).toBe('Selected source is outside the exact topic');
    }
  });
});
