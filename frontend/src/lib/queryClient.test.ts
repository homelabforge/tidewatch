import { describe, it, expect } from 'vitest';
import { ApiError } from '../services/api';
import { isNonRetryableHTTP, shouldRetry } from './queryClient';

describe('isNonRetryableHTTP', () => {
  it.each([400, 401, 409])('returns true for ApiError with status %i', (status) => {
    expect(isNonRetryableHTTP(new ApiError(status, null, ''))).toBe(true);
  });

  it.each([403, 404, 408, 422, 429, 500, 502, 503])(
    'returns false for ApiError with status %i',
    (status) => {
      expect(isNonRetryableHTTP(new ApiError(status, null, ''))).toBe(false);
    },
  );

  it('returns false for non-ApiError values', () => {
    expect(isNonRetryableHTTP(new Error('boom'))).toBe(false);
    expect(isNonRetryableHTTP(null)).toBe(false);
    expect(isNonRetryableHTTP(undefined)).toBe(false);
    expect(isNonRetryableHTTP({ status: 500 })).toBe(false);
  });
});

describe('shouldRetry', () => {
  it.each([400, 401, 409])('skips retry for non-retryable status %i', (status) => {
    const err = new ApiError(status, null, '');
    expect(shouldRetry(0, err)).toBe(false);
    expect(shouldRetry(1, err)).toBe(false);
    expect(shouldRetry(2, err)).toBe(false);
  });

  it('retries up to 3 times for retryable errors (e.g. 500)', () => {
    const err = new ApiError(500, null, '');
    expect(shouldRetry(0, err)).toBe(true);
    expect(shouldRetry(1, err)).toBe(true);
    expect(shouldRetry(2, err)).toBe(true);
    expect(shouldRetry(3, err)).toBe(false);
  });

  it('retries non-ApiError failures up to 3 times (network errors)', () => {
    const err = new Error('network failure');
    expect(shouldRetry(0, err)).toBe(true);
    expect(shouldRetry(2, err)).toBe(true);
    expect(shouldRetry(3, err)).toBe(false);
  });
});
