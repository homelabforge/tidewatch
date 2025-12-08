// Mock data for Tidewatch tests

export const mockContainer = {
  id: 1,
  name: 'nginx',
  image: 'nginx',
  current_tag: '1.20',
  registry: 'docker.io',
  policy: 'manual' as const,
  scope: 'minor' as const,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

export const mockContainers = [
  mockContainer,
  {
    id: 2,
    name: 'postgres',
    image: 'postgres',
    current_tag: '15.0',
    registry: 'docker.io',
    policy: 'auto' as const,
    scope: 'patch' as const,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 3,
    name: 'redis',
    image: 'redis',
    current_tag: '7.0',
    registry: 'docker.io',
    policy: 'security' as const,
    scope: 'major' as const,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
]

export const mockUpdate = {
  id: 1,
  container_id: 1,
  container_name: 'nginx',
  from_tag: '1.20',
  to_tag: '1.21',
  status: 'pending' as const,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

export const mockUpdates = [
  mockUpdate,
  {
    id: 2,
    container_id: 2,
    container_name: 'postgres',
    from_tag: '15.0',
    to_tag: '15.1',
    status: 'approved' as const,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 3,
    container_id: 3,
    container_name: 'redis',
    from_tag: '7.0',
    to_tag: '7.2',
    status: 'applied' as const,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
]

export const mockUser = {
  id: 1,
  username: 'admin',
  email: 'admin@example.com',
  full_name: 'Test Admin',
  created_at: '2025-01-01T00:00:00Z',
}

export const mockAuthResponse = {
  access_token: 'mock-jwt-token-123',
  token_type: 'bearer',
}

export const mockSettings = {
  auto_update_enabled: false,
  check_interval: 60,
  auto_restart_enabled: true,
  max_retries: 3,
  notification_enabled: false,
}

export const mockHistoryEvent = {
  id: 1,
  container_id: 1,
  container_name: 'nginx',
  from_tag: '1.19',
  to_tag: '1.20',
  status: 'success' as const,
  created_at: '2024-12-01T00:00:00Z',
}

export const mockHistoryEvents = [
  mockHistoryEvent,
  {
    id: 2,
    container_id: 2,
    container_name: 'postgres',
    from_tag: '14.0',
    to_tag: '15.0',
    status: 'success' as const,
    created_at: '2024-12-15T00:00:00Z',
  },
  {
    id: 3,
    container_id: 1,
    container_name: 'nginx',
    from_tag: '1.20',
    to_tag: '1.21',
    status: 'failed' as const,
    error: 'Health check failed',
    created_at: '2025-01-02T00:00:00Z',
  },
]

export const mockNotificationConfig = {
  discord: {
    enabled: false,
    webhook_url: '',
  },
  slack: {
    enabled: false,
    webhook_url: '',
  },
  telegram: {
    enabled: false,
    bot_token: '',
    chat_id: '',
  },
  email: {
    enabled: false,
    smtp_host: '',
    smtp_port: 587,
    smtp_user: '',
    from_address: '',
    to_addresses: [],
  },
}

export const mockAnalytics = {
  total_containers: 10,
  total_updates: 50,
  pending_updates: 5,
  success_rate: 92.5,
  recent_failures: 2,
}

export const mockSSEEvent = {
  type: 'update_available',
  data: {
    container_name: 'nginx',
    from_tag: '1.20',
    to_tag: '1.21',
  },
}
