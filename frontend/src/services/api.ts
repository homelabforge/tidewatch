import type {
  Container,
  Update,
  UpdateHistory,
  UnifiedHistoryEvent,
  SystemInfo,
  ContainerMetrics,
  ContainerLogs,
  BackupListResponse,
  TestConnectionResult,
  SettingValue,
  RestartState,
  EnableRestartConfig,
  RestartLog,
  RestartStats,
  DependencyInfo,
  UpdateWindowInfo,
  AnalyticsSummary,
  AppDependenciesResponse,
  BatchDependencyUpdateResponse,
  DockerfileDependenciesResponse,
  HttpServersResponse,
  CheckJobStartResponse,
  CheckJobResult,
  CheckJobSummary,
  RollbackHistoryResponse,
  RollbackResponse,
} from '../types';
import type { PreviewData } from '../components/DependencyUpdatePreviewModal';
import type {
  AuthStatusResponse,
  SetupRequest,
  SetupResponse,
  LoginRequest,
  TokenResponse,
  UserProfile,
  UpdateProfileRequest,
  ChangePasswordRequest,
  MessageResponse,
  OIDCConfig,
  OIDCLinkRequest,
  OIDCTestResult,
} from '../types/auth';

const API_BASE = '/api/v1';

// Store CSRF token in memory (captured from response headers)
let csrfToken: string | null = null;

// Helper function to get CSRF token
function getCsrfToken(): string | null {
  return csrfToken;
}

// Helper function to update CSRF token from response headers
function updateCsrfToken(response: Response): void {
  // Headers.get() is case-insensitive per spec, but be explicit
  const token = response.headers.get('x-csrf-token') || response.headers.get('X-CSRF-Token');
  if (token) {
    csrfToken = token;
    console.log('[CSRF] Token updated:', token.substring(0, 10) + '...');
  }
}

// Helper function for API calls with CSRF protection
async function apiCall<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers instanceof Headers
      ? Object.fromEntries(options.headers.entries())
      : options?.headers as Record<string, string>),
  };

  // Add CSRF token for unsafe methods (POST, PUT, DELETE, PATCH)
  const method = options?.method?.toUpperCase() || 'GET';
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
      console.log(`[CSRF] Including token in ${method} ${endpoint}:`, csrfToken.substring(0, 10) + '...');
    } else {
      console.warn(`[CSRF] No token available for ${method} ${endpoint}`);
    }
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
    credentials: 'same-origin', // Ensure cookies are sent
  });

  // Update CSRF token from response headers if present
  updateCsrfToken(response);

  if (!response.ok) {
    // Handle 404 on auth endpoints - silently fail to allow auth-disabled mode
    if (response.status === 404 && endpoint.startsWith('/auth/')) {
      const error = await response.text();
      throw new Error(error || `API call failed: ${response.statusText}`);
    }

    // Handle 401 Unauthorized - session expired
    if (response.status === 401) {
      // Check if user was previously authenticated
      const wasAuthenticated = sessionStorage.getItem('wasAuthenticated') === 'true';

      if (wasAuthenticated) {
        // Import toast dynamically to avoid circular dependency
        import('sonner').then(({ toast }) => {
          toast.error('Your session has expired. Please log in again.');
        });
      }

      // Signal auth context via sessionStorage (triggers across tabs)
      sessionStorage.setItem('auth:401', Date.now().toString());
      sessionStorage.removeItem('wasAuthenticated');
    }

    const error = await response.text();
    throw new Error(error || `API call failed: ${response.statusText}`);
  }

  return response.json();
}

// Container API
export const containerApi = {
  // Use trailing slash to match FastAPI routes and avoid redirects
  getAll: () => apiCall<Container[]>('/containers/'),

  getById: (id: number) => apiCall<Container>(`/containers/${id}`),

  sync: () => apiCall<{ message: string; containers_found: number; stats: Record<string, unknown>; success: boolean }>('/containers/sync', {
    method: 'POST',
  }),

  update: (id: number, data: Partial<Container>) =>
    apiCall<Container>(`/containers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiCall<{ message: string }>(`/containers/${id}`, {
      method: 'DELETE',
    }),

  checkForUpdates: (id: number) =>
    apiCall<{ update: Update | null; success: boolean; message: string }>(`/updates/check/${id}`, {
      method: 'POST',
    }),

  restart: (id: number) =>
    apiCall<{ message: string }>(`/containers/${id}/restart`, {
      method: 'POST',
    }),

  recheckUpdates: (id: number) =>
    apiCall<{ success: boolean; update_found: boolean; latest_tag: string | null; latest_major_tag: string | null; message: string }>(`/containers/${id}/recheck-updates`, {
      method: 'POST',
    }),

  getLogs: (id: number, tail: number = 100) =>
    apiCall<ContainerLogs>(`/containers/${id}/logs?tail=${tail}`),

  getMetrics: (id: number) =>
    apiCall<ContainerMetrics>(`/containers/${id}/metrics`),

  getHistory: (id: number) =>
    apiCall<UpdateHistory[]>(`/containers/${id}/history`),

  getDependencies: (id: number) =>
    apiCall<DependencyInfo>(`/containers/${id}/dependencies`),

  updateDependencies: (id: number, dependencies: string[]) =>
    apiCall<{ success: boolean; message: string }>(`/containers/${id}/dependencies`, {
      method: 'PUT',
      body: JSON.stringify(dependencies),
    }),

  getUpdateWindow: (id: number) =>
    apiCall<UpdateWindowInfo>(`/containers/${id}/update-window`),

  updateUpdateWindow: (id: number, window: string | null) =>
    apiCall<{ success: boolean; message: string }>(`/containers/${id}/update-window`, {
      method: 'PUT',
      body: JSON.stringify({ update_window: window }),
    }),

  detectHealthCheck: (id: number) =>
    apiCall<{ health_check_url: string | null; method: string; confidence: string }>(`/containers/${id}/detect-health-check`, {
      method: 'POST',
    }),

  detectReleaseSource: (id: number) =>
    apiCall<{ release_source: string | null; confidence: string; source_type: string }>(`/containers/${id}/detect-release-source`, {
      method: 'POST',
    }),

  getAppDependencies: (id: number) =>
    apiCall<AppDependenciesResponse>(`/containers/${id}/app-dependencies`),

  scanAppDependencies: (id: number) =>
    apiCall<{ message: string; dependencies_found: number; updates_available: number }>(`/containers/${id}/app-dependencies/scan`, {
      method: 'POST',
    }),

  scanMyProjects: () =>
    apiCall<{ success: boolean; results: { added: number; updated: number; skipped: number; errors?: string[] } }>('/containers/scan-my-projects', {
      method: 'POST',
    }),

  getDockerfileDependencies: (id: number) =>
    apiCall<DockerfileDependenciesResponse>(`/containers/${id}/dockerfile-dependencies`),

  scanDockerfileDependencies: (id: number) =>
    apiCall<{ success: boolean; message: string; dependencies_found: number; updates_available: number }>(`/containers/${id}/dockerfile-dependencies/scan`, {
      method: 'POST',
    }),

  checkAllDockerfileUpdates: () =>
    apiCall<{ success: boolean; message: string; total_scanned: number; updates_found: number }>('/containers/dockerfile-dependencies/check-updates', {
      method: 'POST',
    }),

  getHttpServers: (id: number) =>
    apiCall<HttpServersResponse>(`/containers/${id}/http-servers`),

  scanHttpServers: (id: number) =>
    apiCall<{ success: boolean; message: string; servers_found: number; updates_available: number }>(`/containers/${id}/http-servers/scan`, {
      method: 'POST',
    }),
};

// Update API
export const updateApi = {
  // Trailing slash to avoid redirect that can downgrade scheme
  getAll: () => apiCall<Update[]>('/updates/'),

  get: (id: number) => apiCall<Update>(`/updates/${id}`),

  approve: (id: number) =>
    apiCall<Update>(`/updates/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        approved: true,
        approved_by: 'user',
      }),
    }),

  reject: (id: number, reason?: string) =>
    apiCall<Update>(`/updates/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  cancelRetry: (id: number) =>
    apiCall<Update>(`/updates/${id}/cancel-retry`, {
      method: 'POST',
    }),

  delete: (id: number) =>
    apiCall<{ success: boolean; message: string }>(`/updates/${id}`, {
      method: 'DELETE',
    }),

  apply: (id: number) =>
    apiCall<{ message: string; history_id: number }>(`/updates/${id}/apply`, {
      method: 'POST',
    }),

  // Background check job methods
  checkAll: () =>
    apiCall<CheckJobStartResponse>('/updates/check', {
      method: 'POST',
    }),

  getCheckJob: (jobId: number) =>
    apiCall<CheckJobResult>(`/updates/check/${jobId}`),

  cancelCheckJob: (jobId: number) =>
    apiCall<{ success: boolean; message: string }>(`/updates/check/${jobId}/cancel`, {
      method: 'POST',
    }),

  getCheckHistory: (limit: number = 20) =>
    apiCall<CheckJobSummary[]>(`/updates/check/history?limit=${limit}`),

  snooze: (id: number) =>
    apiCall<{ success: boolean; message: string; snoozed_until: string }>(`/updates/${id}/snooze`, {
      method: 'POST',
    }),

  removeContainer: (id: number) =>
    apiCall<{ success: boolean; message: string }>(`/updates/${id}/remove-container`, {
      method: 'POST',
    }),

  getSecurity: () => apiCall<Update[]>('/updates/security'),

  getSchedulerStatus: () =>
    apiCall<{
      success: boolean;
      scheduler: {
        running: boolean;
        next_run: string;
        last_check: string;
        schedule: string;
      };
    }>('/updates/scheduler/status'),

  reloadScheduler: () =>
    apiCall<{ success: boolean; message: string }>('/updates/scheduler/reload', {
      method: 'POST',
    }),
};

// History API
export const historyApi = {
  // Trailing slash to avoid redirect that can downgrade scheme
  getAll: () => apiCall<UnifiedHistoryEvent[]>('/history/'),

  getById: (id: number) => apiCall<UpdateHistory>(`/history/${id}`),

  rollback: (id: number) =>
    apiCall<{ message: string }>(`/history/${id}/rollback`, {
      method: 'POST',
    }),
};

// Settings API
export const settingsApi = {
  getAll: () => apiCall<SettingValue[]>('/settings/'),

  get: (key: string) => apiCall<SettingValue>(`/settings/${key}`),

  update: (key: string, value: unknown) =>
    apiCall<SettingValue>(`/settings/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),

  reset: () =>
    apiCall<{ success: boolean; message: string }>('/settings/reset', {
      method: 'POST',
    }),

  getCategories: () =>
    apiCall<Array<{ category: string; settings: SettingValue[] }>>('/settings/categories'),

  testDocker: () =>
    apiCall<TestConnectionResult>('/settings/test/docker', {
      method: 'POST',
    }),

  testDockerHub: () =>
    apiCall<TestConnectionResult>('/settings/test/dockerhub', {
      method: 'POST',
    }),

  testGHCR: () =>
    apiCall<TestConnectionResult>('/settings/test/ghcr', {
      method: 'POST',
    }),

  testVulnForge: () =>
    apiCall<TestConnectionResult>('/settings/test/vulnforge', {
      method: 'POST',
    }),

  testNtfy: () =>
    apiCall<TestConnectionResult>('/settings/test/ntfy', {
      method: 'POST',
    }),

  testGotify: () =>
    apiCall<TestConnectionResult>('/settings/test/gotify', {
      method: 'POST',
    }),

  testPushover: () =>
    apiCall<TestConnectionResult>('/settings/test/pushover', {
      method: 'POST',
    }),

  testSlack: () =>
    apiCall<TestConnectionResult>('/settings/test/slack', {
      method: 'POST',
    }),

  testDiscord: () =>
    apiCall<TestConnectionResult>('/settings/test/discord', {
      method: 'POST',
    }),

  testTelegram: () =>
    apiCall<TestConnectionResult>('/settings/test/telegram', {
      method: 'POST',
    }),

  testEmail: () =>
    apiCall<TestConnectionResult>('/settings/test/email', {
      method: 'POST',
    }),
};

// Backup API
export const backupApi = {
  list: () => apiCall<BackupListResponse>('/backup/list'),

  create: () =>
    apiCall<{ message: string; filename: string }>('/backup/create', {
      method: 'POST',
    }),

  upload: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    const headers: HeadersInit = {};
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }

    const response = await fetch(`${API_BASE}/backup/upload`, {
      method: 'POST',
      body: formData,
      headers,
      credentials: 'same-origin',
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `Upload failed: ${response.statusText}`);
    }

    return response.json();
  },

  download: (filename: string) => `${API_BASE}/backup/download/${filename}`,

  restore: (filename: string) =>
    apiCall<{ message: string }>(`/backup/restore/${filename}`, {
      method: 'POST',
    }),

  delete: (filename: string) =>
    apiCall<{ message: string }>(`/backup/${filename}`, {
      method: 'DELETE',
    }),
};

// System API
export const systemApi = {
  getInfo: () => apiCall<SystemInfo>('/system/info'),

  health: () => apiCall<{ status: string }>('/health'),

  version: () => apiCall<{ version: string; docker_version: string }>('/system/version'),
};

// Restart API
export const restartApi = {
  getState: (id: number) =>
    apiCall<RestartState>(`/restarts/${id}/state`),

  enable: (id: number, config: EnableRestartConfig) =>
    apiCall<{ success: boolean; message: string; state: RestartState }>(`/restarts/${id}/enable`, {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  disable: (id: number, reason?: string) =>
    apiCall<{ success: boolean; message: string }>(`/restarts/${id}/disable`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  reset: (id: number) =>
    apiCall<{ success: boolean; message: string }>(`/restarts/${id}/reset`, {
      method: 'POST',
    }),

  pause: (id: number, duration_seconds: number, reason?: string) =>
    apiCall<{ success: boolean; message: string; paused_until: string }>(`/restarts/${id}/pause`, {
      method: 'POST',
      body: JSON.stringify({ duration_seconds, reason }),
    }),

  resume: (id: number) =>
    apiCall<{ success: boolean; message: string }>(`/restarts/${id}/resume`, {
      method: 'POST',
    }),

  getHistory: (id: number, page: number = 1, page_size: number = 50) =>
    apiCall<{ logs: RestartLog[]; total: number; page: number; page_size: number }>(`/restarts/${id}/history?page=${page}&page_size=${page_size}`),

  manualRestart: (id: number, reason?: string) =>
    apiCall<{ success: boolean; message: string }>(`/restarts/${id}/manual-restart`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  getStats: () =>
    apiCall<RestartStats>('/restarts/stats'),
};

// Analytics API
export const analyticsApi = {
  getSummary: (days: number = 30) =>
    apiCall<AnalyticsSummary>(`/analytics/summary?days=${days}`),
};

// Authentication API
export const authApi = {
  // Auth status & setup
  getStatus: () => apiCall<AuthStatusResponse>('/auth/status'),

  setup: (data: SetupRequest) =>
    apiCall<SetupResponse>('/auth/setup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  cancelSetup: () =>
    apiCall<MessageResponse>('/auth/cancel-setup', {
      method: 'POST',
    }),

  // Local authentication
  login: (data: LoginRequest) =>
    apiCall<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  logout: () =>
    apiCall<MessageResponse>('/auth/logout', {
      method: 'POST',
    }),

  getMe: () => apiCall<UserProfile>('/auth/me'),

  updateProfile: (data: UpdateProfileRequest) =>
    apiCall<UserProfile>('/auth/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  changePassword: (data: ChangePasswordRequest) =>
    apiCall<MessageResponse>('/auth/password', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // OIDC authentication
  oidc: {
    getConfig: () => apiCall<OIDCConfig>('/auth/oidc/config'),

    updateConfig: (data: OIDCConfig) =>
      apiCall<MessageResponse>('/auth/oidc/config', {
        method: 'PUT',
        body: JSON.stringify(data),
      }),

    testConnection: (data: OIDCConfig) =>
      apiCall<OIDCTestResult>('/auth/oidc/test', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    linkAccount: (data: OIDCLinkRequest) =>
      apiCall<TokenResponse>('/auth/oidc/link-account', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  },
};

// Dependencies API
const dependenciesApi = {
  // Dockerfile Dependencies
  ignoreDockerfile: (id: number, reason?: string) =>
    apiCall(`/dependencies/dockerfile/${id}/ignore`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  unignoreDockerfile: (id: number) =>
    apiCall(`/dependencies/dockerfile/${id}/unignore`, {
      method: 'POST',
    }),

  previewDockerfileUpdate: (id: number, newVersion: string) =>
    apiCall<PreviewData>(`/dependencies/dockerfile/${id}/preview?new_version=${encodeURIComponent(newVersion)}`),

  updateDockerfile: async (id: number, newVersion: string) => {
    const response = await apiCall<{ success: boolean; error?: string }>(`/dependencies/dockerfile/${id}/update`, {
      method: 'POST',
      body: JSON.stringify({ new_version: newVersion }),
    });
    if (!response.success) {
      throw new Error(response.error || 'Update failed');
    }
    return response;
  },

  // HTTP Servers
  ignoreHttpServer: (id: number, reason?: string) =>
    apiCall(`/dependencies/http-servers/${id}/ignore`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  unignoreHttpServer: (id: number) =>
    apiCall(`/dependencies/http-servers/${id}/unignore`, {
      method: 'POST',
    }),

  previewHttpServerUpdate: (id: number, newVersion: string) =>
    apiCall<PreviewData>(`/dependencies/http-servers/${id}/preview?new_version=${encodeURIComponent(newVersion)}`),

  updateHttpServer: async (id: number, newVersion: string) => {
    const response = await apiCall<{ success: boolean; error?: string }>(`/dependencies/http-servers/${id}/update`, {
      method: 'POST',
      body: JSON.stringify({ new_version: newVersion }),
    });
    if (!response.success) {
      throw new Error(response.error || 'Update failed');
    }
    return response;
  },

  // App Dependencies
  ignoreAppDependency: (id: number, reason?: string) =>
    apiCall(`/dependencies/app-dependencies/${id}/ignore`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  unignoreAppDependency: (id: number) =>
    apiCall(`/dependencies/app-dependencies/${id}/unignore`, {
      method: 'POST',
    }),

  previewAppDependencyUpdate: (id: number, newVersion: string) =>
    apiCall<PreviewData>(`/dependencies/app-dependencies/${id}/preview?new_version=${encodeURIComponent(newVersion)}`),

  updateAppDependency: async (id: number, newVersion: string) => {
    const response = await apiCall<{ success: boolean; error?: string }>(`/dependencies/app-dependencies/${id}/update`, {
      method: 'POST',
      body: JSON.stringify({ new_version: newVersion }),
    });
    if (!response.success) {
      throw new Error(response.error || 'Update failed');
    }
    return response;
  },

  // Batch update multiple app dependencies
  batchUpdateAppDependencies: (dependencyIds: number[]) =>
    apiCall<BatchDependencyUpdateResponse>('/dependencies/app-dependencies/batch/update', {
      method: 'POST',
      body: JSON.stringify({ dependency_ids: dependencyIds }),
    }),

  // Rollback - Dockerfile Dependencies
  getDockerfileRollbackHistory: (id: number, limit: number = 10) =>
    apiCall<RollbackHistoryResponse>(`/dependencies/dockerfile/${id}/rollback-history?limit=${limit}`),

  rollbackDockerfile: (id: number, targetVersion: string) =>
    apiCall<RollbackResponse>(`/dependencies/dockerfile/${id}/rollback`, {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion }),
    }),

  // Rollback - HTTP Servers
  getHttpServerRollbackHistory: (id: number, limit: number = 10) =>
    apiCall<RollbackHistoryResponse>(`/dependencies/http-servers/${id}/rollback-history?limit=${limit}`),

  rollbackHttpServer: (id: number, targetVersion: string) =>
    apiCall<RollbackResponse>(`/dependencies/http-servers/${id}/rollback`, {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion }),
    }),

  // Rollback - App Dependencies
  getAppDependencyRollbackHistory: (id: number, limit: number = 10) =>
    apiCall<RollbackHistoryResponse>(`/dependencies/app-dependencies/${id}/rollback-history?limit=${limit}`),

  rollbackAppDependency: (id: number, targetVersion: string) =>
    apiCall<RollbackResponse>(`/dependencies/app-dependencies/${id}/rollback`, {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion }),
    }),
};

// Export combined API
export const api = {
  containers: containerApi,
  updates: updateApi,
  history: historyApi,
  settings: settingsApi,
  backup: backupApi,
  system: systemApi,
  restarts: restartApi,
  analytics: analyticsApi,
  auth: authApi,
  dependencies: dependenciesApi,
};

export default api;
