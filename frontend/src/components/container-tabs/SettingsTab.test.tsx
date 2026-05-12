/**
 * Tests for SettingsTab Phase 5 / Pattern F behaviors:
 * - My-Project toggle goes through a mutation (no prop mutation).
 * - Toggle invalidates ['containers','all'] so ContainerModal's
 *   `useContainer` selector reflects the new value reactively.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders as render } from '../../__tests__/test-utils';
import SettingsTab from './SettingsTab';
import { api } from '../../services/api';
import type { Container } from '../../types';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  api: {
    containers: {
      update: vi.fn(),
      getDependencies: vi.fn(),
      getAll: vi.fn(),
      detectHealthCheck: vi.fn(),
      detectReleaseSource: vi.fn(),
      recheckUpdates: vi.fn(),
      updateDependencies: vi.fn(),
      updateUpdateWindow: vi.fn(),
    },
    settings: { getAll: vi.fn() },
    restarts: {
      getState: vi.fn(),
      enable: vi.fn(),
      disable: vi.fn(),
      reset: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
    },
  },
}));

const mockContainer = {
  id: 7,
  name: 'web',
  policy: 'monitor',
  scope: 'minor',
  is_my_project: false,
  include_prereleases: null,
  version_track: null,
  vulnforge_enabled: false,
  health_check_method: 'auto',
  health_check_url: null,
  health_check_has_auth: false,
  release_source: null,
  auto_restart_enabled: false,
  update_window: null,
  dependencies: [],
  dependents: [],
} as unknown as Container;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.settings.getAll).mockResolvedValue([
    { key: 'my_projects_enabled', value: 'true' },
  ] as never);
  vi.mocked(api.containers.getDependencies).mockResolvedValue({
    dependencies: [],
    dependents: [],
  } as never);
  vi.mocked(api.containers.getAll).mockResolvedValue([] as never);
});

describe('SettingsTab — Pattern F (My-Project toggle)', () => {
  it('toggle calls api.containers.update + invalidates [containers,all] without mutating the prop', async () => {
    vi.mocked(api.containers.update).mockResolvedValue({
      ...mockContainer,
      is_my_project: true,
    } as never);

    const { queryClient } = render(<SettingsTab container={mockContainer} />);
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(screen.getByText('Add to My Projects')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Add to My Projects'));

    await waitFor(() => {
      expect(api.containers.update).toHaveBeenCalledWith(mockContainer.id, {
        is_my_project: true,
      });
      expect(spy).toHaveBeenCalledWith({ queryKey: ['containers', 'all'] });
    });

    // Prop must NOT have been mutated by the handler.
    expect(mockContainer.is_my_project).toBe(false);
  });
});
