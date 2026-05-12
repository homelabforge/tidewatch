/**
 * Tests for AuthContext same-tab 401 handling.
 *
 * Verifies that dispatching the `auth:401` CustomEvent in the same tab flips
 * the provider from authenticated to unauthenticated. The pre-existing
 * `storage` listener handles cross-tab cases (or rather, would, if the
 * browser ever fires it for the writing tab — which it doesn't).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useContext } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { AuthContext, AuthProvider } from './AuthContext';

vi.mock('../services/api', () => ({
  authApi: {
    getStatus: vi.fn(),
    getMe: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { authApi } from '../services/api';

function AuthProbe() {
  const ctx = useContext(AuthContext);
  if (!ctx) return <div>no-context</div>;
  return (
    <div>
      <span data-testid="loading">{String(ctx.isLoading)}</span>
      <span data-testid="authed">{String(ctx.isAuthenticated)}</span>
    </div>
  );
}

describe('AuthContext same-tab 401 handling', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(authApi.getStatus).mockResolvedValue({
      setup_complete: true,
      auth_mode: 'local',
      oidc_enabled: false,
    });
    vi.mocked(authApi.getMe).mockResolvedValue({
      id: '1',
      username: 'admin',
      email: 'admin@example.test',
      full_name: 'Admin',
      auth_method: 'local',
      oidc_provider: null,
      created_at: '2026-01-01T00:00:00Z',
      last_login: '2026-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('clears authentication when `auth:401` is dispatched in the same tab', async () => {
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authed').textContent).toBe('true');
    });

    act(() => {
      window.dispatchEvent(new CustomEvent('auth:401'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('authed').textContent).toBe('false');
    });
  });
});
