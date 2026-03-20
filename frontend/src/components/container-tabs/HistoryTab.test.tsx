import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import HistoryTab from './HistoryTab';
import { api } from '../../services/api';
import type { Container, HistoryItem } from '../../types';

// Mock dependencies
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../StatusBadge', () => ({
  default: ({ status }: { status: string }) => <span>{status}</span>,
}));
vi.mock('../../services/api', () => ({
  api: {
    history: { rollback: vi.fn() },
    containers: { getDetails: vi.fn() },
  },
}));

const mockContainer = { id: 1, name: 'nginx' } as Container;

function makeHistoryItem(overrides: Partial<HistoryItem> = {}): HistoryItem {
  return {
    id: 1,
    container_id: 1,
    from_tag: '1.19',
    to_tag: '1.20',
    status: 'success',
    triggered_by: 'auto',
    can_rollback: false,
    started_at: '2025-01-15T10:00:00Z',
    completed_at: '2025-01-15T10:02:00Z',
    cves_fixed: [],
    ...overrides,
  } as HistoryItem;
}

function mockFetchWithHistory(items: HistoryItem[]) {
  vi.mocked(api.containers.getDetails).mockResolvedValue({ history: items });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('HistoryTab — data_backup_status badge', () => {
  it('renders green success badge when data_backup_status is "success"', async () => {
    mockFetchWithHistory([makeHistoryItem({ data_backup_status: 'success' })]);

    render(<HistoryTab container={mockContainer} onClose={vi.fn()} />);

    // Wait for history to load — both status badge and backup badge show 'success'
    await waitFor(() => {
      expect(screen.getAllByText('success').length).toBeGreaterThanOrEqual(1);
    });

    // The data backup badge is the one with the green class
    const badges = screen.getAllByText('success');
    const backupBadge = badges.find((el) => el.className.includes('text-green-400'));
    expect(backupBadge).toBeDefined();
  });

  it('renders red failed badge when data_backup_status is "failed"', async () => {
    mockFetchWithHistory([makeHistoryItem({ data_backup_status: 'failed' })]);

    render(<HistoryTab container={mockContainer} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('failed')).toBeInTheDocument();
    });

    const badge = screen.getByText('failed');
    expect(badge.className).toContain('text-red-400');
  });

  it('does not render the Data Backup section when data_backup_status is absent', async () => {
    mockFetchWithHistory([makeHistoryItem({ data_backup_status: undefined })]);

    render(<HistoryTab container={mockContainer} onClose={vi.fn()} />);

    await waitFor(() => {
      // Wait for history to load (to_tag appears in the rendered item)
      expect(screen.getByText('1.20')).toBeInTheDocument();
    });

    expect(screen.queryByText('Data Backup:')).not.toBeInTheDocument();
  });
});
