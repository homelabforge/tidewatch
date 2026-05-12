/**
 * Tests for DependenciesTab Phase 5 behaviors:
 * - No scan on mount (POST endpoints must not fire from the read query).
 * - Explicit rescan triggers POST + invalidates the dep type key + summary.
 * - Ignore mutation invalidates type key + summary + history.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders as render } from '../../__tests__/test-utils';
import DependenciesTab from './DependenciesTab';
import { api } from '../../services/api';
import type { Container, DockerfileDependency, HttpServer } from '../../types';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  api: {
    containers: {
      getAppDependencies: vi.fn(),
      getDockerfileDependencies: vi.fn(),
      getHttpServers: vi.fn(),
      scanAppDependencies: vi.fn(),
      scanDockerfileDependencies: vi.fn(),
      scanHttpServers: vi.fn(),
    },
    dependencies: {
      ignoreAppDependency: vi.fn(),
      ignoreDockerfile: vi.fn(),
      ignoreHttpServer: vi.fn(),
      unignoreAppDependency: vi.fn(),
      unignoreDockerfile: vi.fn(),
      unignoreHttpServer: vi.fn(),
      updateAppDependency: vi.fn(),
      updateDockerfile: vi.fn(),
      updateHttpServer: vi.fn(),
      batchUpdateAppDependencies: vi.fn(),
    },
  },
}));

// The dependency sections are heavyweight UI; replace them with stubs that
// expose the callbacks we want to exercise.
vi.mock('./dependencies/HttpServerSection', () => ({
  default: ({ onRescan, onIgnore, httpServers }: {
    onRescan: () => Promise<void>;
    onIgnore: (d: HttpServer, t: 'http_server') => void;
    httpServers: { http_servers: HttpServer[] } | null;
  }) => (
    <div>
      <button onClick={onRescan}>Rescan HTTP</button>
      {(httpServers?.http_servers ?? []).map((s) => (
        <button key={s.id} onClick={() => onIgnore(s, 'http_server')}>
          Ignore {s.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock('./dependencies/DockerfileDependencySection', () => ({
  default: ({ onRescan, dockerfileDependencies }: {
    onRescan: () => Promise<void>;
    dockerfileDependencies: { dependencies: DockerfileDependency[] } | null;
  }) => (
    <div>
      <button onClick={onRescan}>Rescan Dockerfile</button>
      <span>Dockerfile count: {dockerfileDependencies?.dependencies?.length ?? 0}</span>
    </div>
  ),
}));

vi.mock('./dependencies/AppDependencySection', () => ({
  default: ({ onRescan }: { onRescan: () => Promise<void> }) => (
    <div>
      <button onClick={onRescan}>Rescan App</button>
    </div>
  ),
}));

vi.mock('../DependencyIgnoreModal', () => ({
  default: ({ onConfirm }: { onConfirm: (reason?: string) => Promise<void> }) => (
    <div data-testid="ignore-modal">
      <button onClick={() => onConfirm('test reason')}>Confirm Ignore</button>
    </div>
  ),
}));
vi.mock('../DependencyUpdatePreviewModal', () => ({ default: () => null }));
vi.mock('../BatchUpdateConfirmModal', () => ({ default: () => null }));
vi.mock('../BatchUpdateResultsModal', () => ({ default: () => null }));
vi.mock('../DependencyRollbackModal', () => ({ default: () => null }));

const mockContainer = {
  id: 7,
  name: 'web',
  is_my_project: true,
} as Container;

const mockHttpServer: HttpServer = {
  id: 42,
  name: 'nginx',
  current_version: '1.20',
  latest_version: '1.21',
  update_available: true,
  ignored: false,
} as HttpServer;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.containers.getAppDependencies).mockResolvedValue({
    dependencies: [],
  } as never);
  vi.mocked(api.containers.getDockerfileDependencies).mockResolvedValue({
    dependencies: [],
  } as never);
  vi.mocked(api.containers.getHttpServers).mockResolvedValue({
    http_servers: [mockHttpServer],
  } as never);
});

describe('DependenciesTab', () => {
  it('does NOT call scan endpoints on mount (read-only on initial render)', async () => {
    render(<DependenciesTab container={mockContainer} />);

    // Wait for initial reads to complete.
    await waitFor(() => {
      expect(api.containers.getDockerfileDependencies).toHaveBeenCalled();
      expect(api.containers.getHttpServers).toHaveBeenCalled();
    });

    expect(api.containers.scanAppDependencies).not.toHaveBeenCalled();
    expect(api.containers.scanDockerfileDependencies).not.toHaveBeenCalled();
    expect(api.containers.scanHttpServers).not.toHaveBeenCalled();
  });

  it('Rescan HTTP triggers scan + invalidates type key + summary', async () => {
    vi.mocked(api.containers.scanHttpServers).mockResolvedValue({
      success: true,
      message: 'scanned',
      servers_found: 1,
    } as never);

    const { queryClient } = render(<DependenciesTab container={mockContainer} />);
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(screen.getByText('Rescan HTTP')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Rescan HTTP'));

    await waitFor(() => {
      expect(api.containers.scanHttpServers).toHaveBeenCalledWith(mockContainer.id);
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['dependencies', 'httpServer', mockContainer.id],
      });
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['containers', 'dependencySummary'],
      });
    });
  });

  it('ignore mutation invalidates type key + summary + history', async () => {
    vi.mocked(api.dependencies.ignoreHttpServer).mockResolvedValue({} as never);

    const { queryClient } = render(<DependenciesTab container={mockContainer} />);
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(screen.getByText(/Ignore nginx/)).toBeInTheDocument();
    });

    // Open the ignore modal via section stub, then confirm.
    fireEvent.click(screen.getByText(/Ignore nginx/));

    await waitFor(() => {
      expect(screen.getByTestId('ignore-modal')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Confirm Ignore'));

    await waitFor(() => {
      expect(api.dependencies.ignoreHttpServer).toHaveBeenCalledWith(
        mockHttpServer.id,
        'test reason',
      );
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['dependencies', 'httpServer', mockContainer.id],
      });
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['containers', 'dependencySummary'],
      });
      expect(spy).toHaveBeenCalledWith({ queryKey: ['history'] });
    });
  });
});
