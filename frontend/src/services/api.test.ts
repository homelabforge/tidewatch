/**
 * Tests for 401 handling in services/api.ts.
 *
 * Every code path that calls `fetch` directly (apiCall + backup.upload) must
 * dispatch the same-tab `auth:401` CustomEvent so `AuthContext` can flip to
 * unauthenticated without waiting for a `storage` event that never arrives
 * in the writing tab.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiError, api } from './api';

function mockFetchResponse(status: number, body: string = ''): void {
  vi.mocked(globalThis.fetch).mockResolvedValueOnce(
    new Response(body, { status }) as Response,
  );
}

describe('api 401 dispatch', () => {
  const spy = vi.fn();
  const listener: EventListener = () => spy();

  beforeEach(() => {
    spy.mockClear();
    window.addEventListener('auth:401', listener);
    sessionStorage.clear();
  });

  afterEach(() => {
    window.removeEventListener('auth:401', listener);
    vi.clearAllMocks();
  });

  it('apiCall dispatches `auth:401` and throws ApiError on 401', async () => {
    mockFetchResponse(401, JSON.stringify({ detail: 'expired' }));

    await expect(api.containers.getAll()).rejects.toBeInstanceOf(ApiError);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem('auth:401')).not.toBeNull();
  });

  it('apiCall does not dispatch on non-401 errors', async () => {
    mockFetchResponse(500, 'boom');

    await expect(api.containers.getAll()).rejects.toBeInstanceOf(ApiError);
    expect(spy).not.toHaveBeenCalled();
  });

  it('backup.upload dispatches `auth:401` on 401', async () => {
    mockFetchResponse(401, 'session expired');

    const file = new File(['payload'], 'backup.tar.gz', {
      type: 'application/gzip',
    });
    await expect(api.backup.upload(file)).rejects.toBeInstanceOf(Error);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem('auth:401')).not.toBeNull();
  });

  it('backup.upload does not dispatch on non-401 errors', async () => {
    mockFetchResponse(500, 'server boom');

    const file = new File(['payload'], 'backup.tar.gz', {
      type: 'application/gzip',
    });
    await expect(api.backup.upload(file)).rejects.toBeInstanceOf(Error);
    expect(spy).not.toHaveBeenCalled();
  });
});
