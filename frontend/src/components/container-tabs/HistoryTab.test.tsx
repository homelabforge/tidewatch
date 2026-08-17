import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders as render } from '../../__tests__/test-utils';
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
    dependencies: {
      unignoreDockerfile: vi.fn(),
      unignoreHttpServer: vi.fn(),
      unignoreAppDependency: vi.fn(),
    },
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
  it.each([
    ['success', 'text-green-400', 'Success'],
    ['failed', 'text-red-400', 'Failed'],
    ['container_missing', 'text-red-400', 'Container Missing'],
    ['partial', 'text-yellow-400', 'Partial'],
  ])('renders the %s backup status as a readable, colour-coded badge', async (
    status,
    expectedClass,
    expectedLabel,
  ) => {
    mockFetchWithHistory([makeHistoryItem({ data_backup_status: status })]);

    render(<HistoryTab container={mockContainer} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(expectedLabel)).toBeInTheDocument();
    });

    expect(screen.getByText(expectedLabel).className).toContain(expectedClass);
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

describe('HistoryTab — cache invalidation', () => {
  it('unignore invalidates details + history + dep summary + dep type key', async () => {
    const item = makeHistoryItem({
      id: 11,
      event_type: 'dependency_ignore',
      status: 'success',
      dependency_id: 5,
      dependency_type: 'app_dependency',
      dependency_name: 'fastapi',
    });
    mockFetchWithHistory([item]);
    vi.mocked(api.dependencies.unignoreAppDependency).mockResolvedValue(
      {} as never,
    );

    const onUpdate = vi.fn();
    const { queryClient } = render(
      <HistoryTab
        container={mockContainer}
        onClose={vi.fn()}
        onUpdate={onUpdate}
      />,
    );
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(screen.getByText(/Unignore/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Unignore/));

    await waitFor(() => {
      expect(api.dependencies.unignoreAppDependency).toHaveBeenCalledWith(5);
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['containers', 'details', mockContainer.id],
      });
      expect(spy).toHaveBeenCalledWith({ queryKey: ['history'] });
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['containers', 'dependencySummary'],
      });
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['dependencies', 'app', mockContainer.id],
      });
      expect(onUpdate).toHaveBeenCalled();
    });
  });
});
