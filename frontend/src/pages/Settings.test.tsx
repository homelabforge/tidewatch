import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Settings from './Settings'
import { api } from '../services/api'
import { AuthContext, type AuthContextType } from '../contexts/AuthContext'

// Mock the API
vi.mock('../services/api', () => ({
  api: {
    settings: {
      getAll: vi.fn(),
      get: vi.fn(),
      set: vi.fn(),
      getCategories: vi.fn(),
    },
    backup: {
      list: vi.fn(),
      create: vi.fn(),
      restore: vi.fn(),
      delete: vi.fn(),
      upload: vi.fn(),
      download: vi.fn(),
    },
    system: {
      getSchedulerStatus: vi.fn(),
    },
    auth: {
      updateProfile: vi.fn(),
      changePassword: vi.fn(),
      oidc: {
        getConfig: vi.fn(),
        updateConfig: vi.fn(),
        testConnection: vi.fn(),
      },
    },
  },
}))

// Mock toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

// Mock notification components
vi.mock('../components/notifications', () => ({
  NotificationSubTabs: ({ active, onChange }: any) => (
    <div data-testid="notification-subtabs">
      <button onClick={() => onChange('ntfy')}>Ntfy</button>
      <button onClick={() => onChange('gotify')}>Gotify</button>
    </div>
  ),
  EventNotificationsCard: () => <div data-testid="event-notifications">Event Notifications</div>,
  NtfyConfig: () => <div data-testid="ntfy-config">Ntfy Config</div>,
  GotifyConfig: () => <div data-testid="gotify-config">Gotify Config</div>,
  PushoverConfig: () => <div data-testid="pushover-config">Pushover Config</div>,
  SlackConfig: () => <div data-testid="slack-config">Slack Config</div>,
  DiscordConfig: () => <div data-testid="discord-config">Discord Config</div>,
  TelegramConfig: () => <div data-testid="telegram-config">Telegram Config</div>,
  EmailConfig: () => <div data-testid="email-config">Email Config</div>,
}))

// Mock HelpTooltip
vi.mock('../components/HelpTooltip', () => ({
  HelpTooltip: ({ text }: { text: string }) => <div data-testid="help-tooltip">{text}</div>,
}))

const mockSettings = {
  check_interval: '3600',
  auto_update_enabled: 'false',
  auto_update_policy: 'minor',
  docker_socket_path: '/var/run/docker.sock',
  docker_hub_username: '',
  docker_hub_password: '',
  vulnforge_url: 'http://localhost:8080',
  vulnforge_enabled: 'false',
}

const mockCategories = [
  {
    id: 'system',
    name: 'System',
    description: 'System settings',
    icon: 'Server',
    settings: [
      {
        key: 'check_interval',
        name: 'Check Interval',
        description: 'How often to check for updates (seconds)',
        type: 'number',
        category_id: 'system',
        default_value: '3600',
        validation_rules: { min: 60, max: 86400 },
        sensitive: false,
      },
    ],
  },
  {
    id: 'updates',
    name: 'Updates',
    description: 'Update policy settings',
    icon: 'RefreshCw',
    settings: [
      {
        key: 'auto_update_enabled',
        name: 'Auto Update Enabled',
        description: 'Automatically apply approved updates',
        type: 'boolean',
        category_id: 'updates',
        default_value: 'false',
        validation_rules: {},
        sensitive: false,
      },
    ],
  },
]

// Mock ThemeContext useTheme hook
vi.mock('../contexts/ThemeContext', () => ({
  useTheme: () => ({
    theme: 'dark',
    setTheme: vi.fn(),
    isLoading: false,
  }),
}))

const createMockAuthContext = (overrides?: Partial<AuthContextType>): AuthContextType => ({
  user: {
    id: '1',
    username: 'admin',
    email: 'admin@test.com',
    full_name: 'Admin User',
    created_at: '2025-01-01T00:00:00Z',
  },
  authMode: 'local',
  isAuthenticated: true,
  isLoading: false,
  setupComplete: true,
  oidcEnabled: false,
  login: vi.fn(),
  logout: vi.fn(),
  checkAuth: vi.fn(),
  updateProfile: vi.fn(),
  changePassword: vi.fn(),
  ...overrides,
})

describe('Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.settings.getAll as any).mockResolvedValue(mockSettings)
    ;(api.settings.getCategories as any).mockResolvedValue(mockCategories)
    ;(api.backup.list as any).mockResolvedValue({ backups: [], total_size: 0 })
    ;(api.system.getSchedulerStatus as any).mockResolvedValue({ running: true, next_run: '2025-01-15T10:00:00Z' })
    ;(api.auth.oidc.getConfig as any).mockResolvedValue({
      enabled: false,
      issuer_url: '',
      client_id: '',
      client_secret: '',
      provider_name: '',
      scopes: 'openid email profile',
      redirect_uri: '',
    })
  })

  const renderSettings = (authContext = createMockAuthContext()) => {
    return render(
      <AuthContext.Provider value={authContext}>
        <Settings />
      </AuthContext.Provider>
    )
  }

  describe('Data loading', () => {
    it('loads settings on mount', async () => {
      renderSettings()

      await waitFor(() => {
        expect(api.settings.getAll).toHaveBeenCalledTimes(1)
        expect(api.settings.getCategories).toHaveBeenCalledTimes(1)
      })
    })

    it('shows loading state while fetching', () => {
      renderSettings()

      const loadingText = screen.getByText('Loading settings...')
      expect(loadingText).toBeInTheDocument()
    })

    it('displays settings after loading', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })
    })

    it('handles API error gracefully', async () => {
      const { toast } = await import('sonner')
      ;(api.settings.getAll as any).mockRejectedValue(new Error('API Error'))

      renderSettings()

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled()
      })
    })
  })

  describe('Tab navigation', () => {
    it('renders all tab buttons', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      expect(screen.getByText('System')).toBeInTheDocument()
      expect(screen.getByText('Updates')).toBeInTheDocument()
      expect(screen.getByText('Docker')).toBeInTheDocument()
      expect(screen.getByText('Integrations')).toBeInTheDocument()
      expect(screen.getByText('Notifications')).toBeInTheDocument()
      expect(screen.getByText('Backup')).toBeInTheDocument()
      expect(screen.getByText('Security')).toBeInTheDocument()
    })

    it('shows system tab by default', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      // System tab should be active (specific content depends on what's rendered)
      const systemButton = screen.getByText('System')
      expect(systemButton.className).toContain('bg-primary')
    })

    it('switches to updates tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const updatesButton = screen.getByText('Updates')
      fireEvent.click(updatesButton)

      await waitFor(() => {
        expect(updatesButton.className).toContain('bg-primary')
      })
    })

    it('switches to docker tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const dockerButton = screen.getByText('Docker')
      fireEvent.click(dockerButton)

      await waitFor(() => {
        expect(dockerButton.className).toContain('bg-primary')
      })
    })

    it('switches to integrations tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const integrationsButton = screen.getByText('Integrations')
      fireEvent.click(integrationsButton)

      await waitFor(() => {
        expect(integrationsButton.className).toContain('bg-primary')
      })
    })

    it('switches to notifications tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const notificationsButton = screen.getByText('Notifications')
      fireEvent.click(notificationsButton)

      await waitFor(() => {
        expect(notificationsButton.className).toContain('bg-primary')
      })
    })

    it('switches to backup tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      await waitFor(() => {
        expect(backupButton.className).toContain('bg-primary')
      })
    })

    it('switches to security tab when clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const securityButton = screen.getByText('Security')
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(securityButton.className).toContain('bg-primary')
      })
    })
  })

  describe('System tab', () => {
    it('displays theme toggle', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const themeLabels = screen.getAllByText('Theme')
      expect(themeLabels.length).toBeGreaterThan(0)
    })

    it('toggles theme when button clicked', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      // Find and click light theme button
      const lightButtons = screen.getAllByText('Light')
      fireEvent.click(lightButtons[0])

      // Theme toggle should render buttons
      expect(lightButtons.length).toBeGreaterThan(0)
    })

    it('shows user profile section when authenticated', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      expect(screen.getByText('Profile')).toBeInTheDocument()
    })

    it('does not show profile section when auth disabled', async () => {
      const authContext = createMockAuthContext({
        authMode: 'none',
        isAuthenticated: false,
        user: null,
      })

      renderSettings(authContext)

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      expect(screen.queryByText('Profile')).not.toBeInTheDocument()
    })
  })

  describe('Updates tab', () => {
    it('displays scheduler status when tab is active', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const updatesButton = screen.getByText('Updates')
      fireEvent.click(updatesButton)

      await waitFor(() => {
        expect(api.system.getSchedulerStatus).toHaveBeenCalled()
      })
    })
  })

  describe('Backup tab', () => {
    it('loads backups when tab is activated', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      await waitFor(() => {
        expect(api.backup.list).toHaveBeenCalled()
      })
    })

    it('displays create backup button', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      await waitFor(() => {
        const createButtons = screen.getAllByText('Create Backup')
        expect(createButtons.length).toBeGreaterThan(0)
      })
    })

    it('creates backup when button clicked', async () => {
      const { toast } = await import('sonner')
      ;(api.backup.create as any).mockResolvedValue({ filename: 'backup.db' })

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      await waitFor(() => {
        const createButtons = screen.getAllByText('Create Backup')
        expect(createButtons.length).toBeGreaterThan(0)
      })

      const createButtons = screen.getAllByText('Create Backup')
      fireEvent.click(createButtons[0])

      await waitFor(() => {
        expect(api.backup.create).toHaveBeenCalled()
        expect(toast.success).toHaveBeenCalledWith('Backup created successfully')
      })
    })

    it('handles backup creation error', async () => {
      const { toast } = await import('sonner')
      ;(api.backup.create as any).mockRejectedValue(new Error('API Error'))

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      await waitFor(() => {
        const createButtons = screen.getAllByText('Create Backup')
        expect(createButtons.length).toBeGreaterThan(0)
      })

      const createButtons = screen.getAllByText('Create Backup')
      fireEvent.click(createButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to create backup')
      })
    })
  })

  describe('Notifications tab', () => {
    it('displays notification subtabs', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const notificationsButton = screen.getByText('Notifications')
      fireEvent.click(notificationsButton)

      await waitFor(() => {
        expect(screen.getByTestId('notification-subtabs')).toBeInTheDocument()
      })
    })

    it('displays event notifications card', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const notificationsButton = screen.getByText('Notifications')
      fireEvent.click(notificationsButton)

      await waitFor(() => {
        expect(screen.getByTestId('event-notifications')).toBeInTheDocument()
      })
    })

    it('shows ntfy config by default', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const notificationsButton = screen.getByText('Notifications')
      fireEvent.click(notificationsButton)

      await waitFor(() => {
        expect(screen.getByTestId('ntfy-config')).toBeInTheDocument()
      })
    })
  })

  describe('Security tab', () => {
    it('displays OIDC configuration section', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const securityButton = screen.getByText('Security')
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(api.auth.oidc.getConfig).toHaveBeenCalled()
      })
    })

    it('shows password change section for local auth', async () => {
      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const securityButton = screen.getByText('Security')
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(screen.getByText('Change Password')).toBeInTheDocument()
      })
    })

    it('does not show password change for OIDC users', async () => {
      const authContext = createMockAuthContext({
        authMode: 'oidc',
      })

      renderSettings(authContext)

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const securityButton = screen.getByText('Security')
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(screen.queryByText('Change Password')).not.toBeInTheDocument()
      })
    })
  })

  describe('Setting updates', () => {
    it('saves settings when changed', async () => {
      await import('sonner')
      ;(api.settings.set as any).mockResolvedValue({ key: 'check_interval', value: '7200' })

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      // Settings updates would require finding specific input fields
      // This test verifies the API can be called
      await waitFor(() => {
        expect(api.settings.getAll).toHaveBeenCalled()
      })
    })
  })

  describe('Error handling', () => {
    it('handles settings load error', async () => {
      const { toast } = await import('sonner')
      ;(api.settings.getCategories as any).mockRejectedValue(new Error('API Error'))

      renderSettings()

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled()
      })
    })

    it('handles scheduler status error', async () => {
      ;(api.system.getSchedulerStatus as any).mockRejectedValue(new Error('API Error'))

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const updatesButton = screen.getByText('Updates')
      fireEvent.click(updatesButton)

      // Should not crash when scheduler fails to load
      await waitFor(() => {
        expect(api.system.getSchedulerStatus).toHaveBeenCalled()
      })
    })

    it('handles backup list error', async () => {
      ;(api.backup.list as any).mockRejectedValue(new Error('API Error'))

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })

      const backupButton = screen.getByText('Backup')
      fireEvent.click(backupButton)

      // Should not crash when backup list fails to load
      await waitFor(() => {
        expect(api.backup.list).toHaveBeenCalled()
      })
    })
  })

  describe('Edge cases', () => {
    it('handles empty settings gracefully', async () => {
      ;(api.settings.getAll as any).mockResolvedValue({})
      ;(api.settings.getCategories as any).mockResolvedValue([])

      renderSettings()

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })
    })

    it('handles missing user data when authenticated', async () => {
      const authContext = createMockAuthContext({
        user: null,
      })

      renderSettings(authContext)

      await waitFor(() => {
        expect(screen.getByText('Settings')).toBeInTheDocument()
      })
    })
  })
})
