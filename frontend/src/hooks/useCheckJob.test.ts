/**
 * Tests for useCheckJob hook SSE event handling.
 *
 * Verifies that:
 * - check-job-started events populate all state fields (regression for 0/37 bug)
 * - check-job-progress events incrementally update state
 * - A new job_id resets counters instead of inheriting stale values
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { CheckJobProgressEvent } from './useEventStream';

// Capture the event handler registered by useCheckJob via useEventStream
let capturedHandlers: Record<string, ((data: CheckJobProgressEvent) => void) | undefined> = {};

vi.mock('./useEventStream', () => ({
  useEventStream: vi.fn((options: Record<string, unknown>) => {
    capturedHandlers = {
      onCheckJobStarted: options.onCheckJobStarted as ((data: CheckJobProgressEvent) => void) | undefined,
      onCheckJobProgress: options.onCheckJobProgress as ((data: CheckJobProgressEvent) => void) | undefined,
      onCheckJobCompleted: options.onCheckJobCompleted as ((data: CheckJobProgressEvent) => void) | undefined,
      onCheckJobFailed: options.onCheckJobFailed as ((data: CheckJobProgressEvent) => void) | undefined,
      onCheckJobCanceled: options.onCheckJobCanceled as ((data: CheckJobProgressEvent) => void) | undefined,
    };
    return { connectionStatus: 'connected', reconnect: vi.fn() };
  }),
}));

vi.mock('../services/api', () => ({
  api: {
    updates: {
      checkAll: vi.fn(),
      getCheckJob: vi.fn(),
      cancelCheckJob: vi.fn(),
    },
  },
}));

vi.mock('sonner', () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

// Import after mocks are set up
import { useCheckJob } from './useCheckJob';
import { api } from '../services/api';

beforeEach(() => {
  vi.clearAllMocks();
  capturedHandlers = {};
});

describe('useCheckJob SSE event handling', () => {
  it('check-job-started sets all fields including status and checkedCount', () => {
    const { result } = renderHook(() => useCheckJob());

    // Simulate check-job-started event with all fields (as fixed in backend)
    act(() => {
      capturedHandlers.onCheckJobStarted?.({
        job_id: 42,
        status: 'running',
        total_count: 37,
        checked_count: 0,
        updates_found: 0,
        errors_count: 0,
        progress_percent: 0,
      });
    });

    expect(result.current.checkJob).not.toBeNull();
    expect(result.current.checkJob!.jobId).toBe(42);
    expect(result.current.checkJob!.status).toBe('running');
    expect(result.current.checkJob!.totalCount).toBe(37);
    expect(result.current.checkJob!.checkedCount).toBe(0);
    expect(result.current.checkJob!.updatesFound).toBe(0);
    expect(result.current.checkJob!.errorsCount).toBe(0);
    expect(result.current.checkJob!.progressPercent).toBe(0);
  });

  it('check-job-progress increments counters', () => {
    const { result } = renderHook(() => useCheckJob());

    // Start
    act(() => {
      capturedHandlers.onCheckJobStarted?.({
        job_id: 42,
        status: 'running',
        total_count: 37,
        checked_count: 0,
        updates_found: 0,
        errors_count: 0,
        progress_percent: 0,
      });
    });

    // Progress
    act(() => {
      capturedHandlers.onCheckJobProgress?.({
        job_id: 42,
        status: 'running',
        total_count: 37,
        checked_count: 5,
        updates_found: 1,
        errors_count: 0,
        current_container: 'nginx',
        progress_percent: 13,
      });
    });

    expect(result.current.checkJob!.checkedCount).toBe(5);
    expect(result.current.checkJob!.updatesFound).toBe(1);
    expect(result.current.checkJob!.currentContainer).toBe('nginx');
    expect(result.current.checkJob!.progressPercent).toBe(13);
  });

  it('new job_id resets counters instead of inheriting stale values', () => {
    const { result } = renderHook(() => useCheckJob());

    // First job completes with some counts
    act(() => {
      capturedHandlers.onCheckJobProgress?.({
        job_id: 1,
        status: 'running',
        total_count: 10,
        checked_count: 10,
        updates_found: 3,
        errors_count: 1,
        progress_percent: 100,
      });
    });

    expect(result.current.checkJob!.updatesFound).toBe(3);
    expect(result.current.checkJob!.errorsCount).toBe(1);

    // New job starts — counters must reset, not inherit from job 1
    act(() => {
      capturedHandlers.onCheckJobStarted?.({
        job_id: 2,
        status: 'running',
        total_count: 37,
        checked_count: 0,
        updates_found: 0,
        errors_count: 0,
        progress_percent: 0,
      });
    });

    expect(result.current.checkJob!.jobId).toBe(2);
    expect(result.current.checkJob!.checkedCount).toBe(0);
    expect(result.current.checkJob!.updatesFound).toBe(0);
    expect(result.current.checkJob!.errorsCount).toBe(0);
  });

  it('startCheckAll initializes state from API response', async () => {
    (api.updates.checkAll as ReturnType<typeof vi.fn>).mockResolvedValue({
      job_id: 99,
      already_running: false,
    });

    const { result } = renderHook(() => useCheckJob());

    await act(async () => {
      await result.current.startCheckAll();
    });

    expect(result.current.checkJob).not.toBeNull();
    expect(result.current.checkJob!.jobId).toBe(99);
    expect(result.current.checkJob!.status).toBe('queued');
    expect(result.current.checkJob!.checkedCount).toBe(0);
    expect(result.current.checkJob!.totalCount).toBe(0);
  });
});
