/**
 * LogsTab Phase 6 — polling behavior (Pattern C).
 *
 * Verified:
 * - Initial fetch fires on mount.
 * - Auto-refresh polls every 2s while enabled.
 * - Toggling Live → Paused stops polling.
 * - Manual Refresh forces a fetch.
 * - Changing `logLines` invalidates the cache key and triggers a fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders as render } from '../../__tests__/test-utils';
import LogsTab from './LogsTab';
import { api } from '../../services/api';
import type { Container } from '../../types';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  api: {
    containers: {
      getLogs: vi.fn(),
    },
  },
}));

const mockContainer = { id: 7, name: 'web' } as Container;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.containers.getLogs).mockResolvedValue({
    logs: ['line-1', 'line-2'],
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('LogsTab — polling (Pattern C)', () => {
  it('fetches logs on mount', async () => {
    render(<LogsTab container={mockContainer} />);
    await waitFor(() => {
      expect(api.containers.getLogs).toHaveBeenCalledWith(mockContainer.id, 100);
    });
  });

  it('polls every 2s while Live is enabled and stops when paused', async () => {
    vi.useFakeTimers();
    render(<LogsTab container={mockContainer} />);

    // Initial fetch
    await vi.waitFor(() => {
      expect(api.containers.getLogs).toHaveBeenCalledTimes(1);
    });

    // Advance 2s → second fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(api.containers.getLogs).toHaveBeenCalledTimes(2);

    // Advance another 2s → third fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(api.containers.getLogs).toHaveBeenCalledTimes(3);

    // Toggle Live → Paused
    fireEvent.click(screen.getByText('Live'));

    // Advance 4s — should NOT fire while paused
    const fetchCountBefore = vi.mocked(api.containers.getLogs).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(vi.mocked(api.containers.getLogs).mock.calls.length).toBe(fetchCountBefore);
  });

  it('manual Refresh button forces a fetch', async () => {
    render(<LogsTab container={mockContainer} />);
    await waitFor(() => {
      expect(api.containers.getLogs).toHaveBeenCalledTimes(1);
    });

    // Pause first to isolate the manual refresh.
    fireEvent.click(screen.getByText('Live'));

    const before = vi.mocked(api.containers.getLogs).mock.calls.length;
    fireEvent.click(screen.getByText('Refresh'));

    await waitFor(() => {
      expect(vi.mocked(api.containers.getLogs).mock.calls.length).toBeGreaterThan(before);
    });
  });

  it('changing logLines triggers a new fetch with the new tail count', async () => {
    render(<LogsTab container={mockContainer} />);
    await waitFor(() => {
      expect(api.containers.getLogs).toHaveBeenCalledWith(mockContainer.id, 100);
    });

    fireEvent.change(screen.getByDisplayValue('100'), { target: { value: '1000' } });

    await waitFor(() => {
      expect(api.containers.getLogs).toHaveBeenCalledWith(mockContainer.id, 1000);
    });
  });
});
