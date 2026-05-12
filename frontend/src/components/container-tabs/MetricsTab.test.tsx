/**
 * MetricsTab Phase 6 — Pattern A (no polling).
 *
 * Verified:
 * - Current metrics load on mount.
 * - No `refetchInterval` (no extra fetches after initial load).
 * - History query is enabled ONLY when the user picks a metric.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders as render } from '../../__tests__/test-utils';
import MetricsTab from './MetricsTab';
import { api } from '../../services/api';
import type { Container } from '../../types';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  api: {
    containers: {
      getMetrics: vi.fn(),
      getMetricsHistory: vi.fn(),
    },
  },
}));

vi.mock('recharts', () => {
  const Stub = () => null;
  return {
    LineChart: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    Line: Stub,
    XAxis: Stub,
    YAxis: Stub,
    CartesianGrid: Stub,
    Tooltip: Stub,
    Legend: Stub,
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  };
});

const mockContainer = { id: 7, name: 'web' } as Container;
const mockMetrics = {
  cpu_percent: 5.5,
  memory_usage: 1024,
  memory_limit: 4096,
  memory_percent: 25,
  network_rx: 100,
  network_tx: 200,
  block_read: 300,
  block_write: 400,
  pids: 3,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.containers.getMetrics).mockResolvedValue(mockMetrics as never);
  vi.mocked(api.containers.getMetricsHistory).mockResolvedValue([] as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('MetricsTab — Pattern A (no polling)', () => {
  it('fetches current metrics on mount', async () => {
    render(<MetricsTab container={mockContainer} />);
    await waitFor(() => {
      expect(api.containers.getMetrics).toHaveBeenCalledTimes(1);
    });
  });

  it('does NOT poll: fetch count stays at 1 across virtual time', async () => {
    vi.useFakeTimers();
    render(<MetricsTab container={mockContainer} />);
    await vi.waitFor(() => {
      expect(api.containers.getMetrics).toHaveBeenCalledTimes(1);
    });

    // Advance well past any reasonable poll interval.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    expect(api.containers.getMetrics).toHaveBeenCalledTimes(1);
  });

  it('does NOT fetch history until a metric is selected', async () => {
    render(<MetricsTab container={mockContainer} />);

    // Wait for the loading spinner to clear and the grid to render.
    await waitFor(() => {
      expect(screen.getByText('CPU Usage')).toBeInTheDocument();
    });
    expect(api.containers.getMetricsHistory).not.toHaveBeenCalled();

    // Click into CPU — selectedMetric flips, history query becomes enabled.
    fireEvent.click(screen.getByText('CPU Usage'));

    await waitFor(() => {
      expect(api.containers.getMetricsHistory).toHaveBeenCalledWith(
        mockContainer.id,
        '24h',
      );
    });
  });
});
