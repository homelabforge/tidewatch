import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '../services/api';

const nonRetryableStatuses = new Set([400, 401, 409]);

export function isNonRetryableHTTP(error: unknown): boolean {
  return error instanceof ApiError && nonRetryableStatuses.has(error.status);
}

export function shouldRetry(failureCount: number, error: unknown): boolean {
  return failureCount < 3 && !isNonRetryableHTTP(error);
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      refetchOnWindowFocus: true,
      retry: shouldRetry,
    },
  },
});
