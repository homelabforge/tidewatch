import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Dashboard from './Dashboard'
import { api } from '../services/api'
import { Container, Update, AnalyticsSummary } from '../types'

// Mock the API
vi.mock('../services/api', () => ({
  api: {
    containers: {
      getAll: vi.fn(),
      sync: vi.fn(),
    },
    updates: {
      getAll: vi.fn(),
      checkAll: vi.fn(),
    },
    analytics: {
      getSummary: vi.fn(),
    },
    settings: {
      getAll: vi.fn(),
    },
  },
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

// Mock lazy-loaded ContainerModal
vi.mock('../components/ContainerModal', () => ({
  default: ({ container, onClose }: { container: Container; onClose: () => void }) => (
    <div data-testid="container-modal">
      <div>Modal for {container.name}</div>
      <button onClick={onClose}>Close Modal</button>
    </div>
  ),
}))

describe('Dashboard', () => {
  const mockContainers: Container[] = [
    {
      id: 1,
      name: 'nginx',
      image: 'nginx',
      current_tag: '1.20',
      current_digest: null,
      registry: 'docker.io',
      compose_file: '/docker/compose.yml',
      service_name: 'nginx',
      policy: 'auto',
      scope: 'minor',
      include_prereleases: false,
      vulnforge_enabled: false,
      current_vuln_count: 0,
      is_my_project: true,
      update_available: true,
      latest_tag: '1.21',
      latest_major_tag: null,
      last_checked: null,
      last_updated: null,
      labels: {},
      health_check_url: null,
      health_check_method: 'GET',
      health_check_has_auth: false,
      release_source: null,
      auto_restart_enabled: false,
      restart_policy: '',
      restart_max_attempts: 3,
      restart_backoff_strategy: 'exponential',
      restart_success_window: 300,
      update_window: null,
      dependencies: [],
      dependents: [],
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    },
    {
      id: 2,
      name: 'postgres',
      image: 'postgres',
      current_tag: '15.0',
      current_digest: null,
      registry: 'docker.io',
      compose_file: '/docker/compose.yml',
      service_name: 'postgres',
      policy: 'manual',
      scope: 'patch',
      include_prereleases: false,
      vulnforge_enabled: false,
      current_vuln_count: 0,
      is_my_project: false,
      update_available: false,
      latest_tag: null,
      latest_major_tag: null,
      last_checked: null,
      last_updated: null,
      labels: {},
      health_check_url: null,
      health_check_method: 'GET',
      health_check_has_auth: false,
      release_source: null,
      auto_restart_enabled: false,
      restart_policy: '',
      restart_max_attempts: 3,
      restart_backoff_strategy: 'exponential',
      restart_success_window: 300,
      update_window: null,
      dependencies: [],
      dependents: [],
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    },
  ]

  const mockUpdates: Update[] = [
    {
      id: 1,
      container_id: 1,
      container_name: 'nginx',
      from_tag: '1.20',
      to_tag: '1.21',
      registry: 'docker.io',
      reason_type: 'security',
      reason_summary: 'Security patch',
      recommendation: 'Highly recommended',
      changelog: null,
      changelog_url: null,
      cves_fixed: ['CVE-2025-1234'],
      current_vulns: 5,
      new_vulns: 0,
      vuln_delta: -5,
      published_date: null,
      image_size_delta: 0,
      status: 'pending',
      scope_violation: 0,
      approved_by: null,
      approved_at: null,
      retry_count: 0,
      max_retries: 3,
      next_retry_at: null,
      last_error: null,
      backoff_multiplier: 3,
      snoozed_until: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    },
  ]

  const mockAnalytics: AnalyticsSummary = {
    period_days: 30,
    total_updates: 10,
    successful_updates: 8,
    failed_updates: 2,
    update_frequency: {},
    vulnerability_trends: {},
    policy_distribution: {},
    avg_update_duration_seconds: 45,
    total_cves_fixed: 15,
  }

  const mockSettings = [
    { key: 'vulnforge_enabled', value: 'true', category: 'integration', description: null, encrypted: false, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    // Default successful API responses
    vi.mocked(api.containers.getAll).mockResolvedValue(mockContainers)
    vi.mocked(api.updates.getAll).mockResolvedValue(mockUpdates)
    vi.mocked(api.analytics.getSummary).mockResolvedValue(mockAnalytics)
    vi.mocked(api.settings.getAll).mockResolvedValue(mockSettings)
  })

  describe('Data loading', () => {
    it('shows loading state initially', () => {
      render(<Dashboard />)
      expect(screen.getByText('Loading containers...')).toBeInTheDocument()
    })

    it('loads all data on mount', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(api.containers.getAll).toHaveBeenCalledTimes(1)
        expect(api.updates.getAll).toHaveBeenCalledTimes(1)
        expect(api.analytics.getSummary).toHaveBeenCalledWith(30)
        expect(api.settings.getAll).toHaveBeenCalledTimes(1)
      })
    })

    it('displays containers after loading', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
        const postgresElements = screen.getAllByText('postgres')
        expect(postgresElements.length).toBeGreaterThan(0)
      })
    })

    it('shows error toast when data loading fails', async () => {
      const { toast } = await import('sonner')
      vi.mocked(api.containers.getAll).mockRejectedValue(new Error('Network error'))

      render(<Dashboard />)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to load data')
      })
    })
  })

  describe('Statistics display', () => {
    it('displays total containers count', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Total Containers')).toBeInTheDocument()
        const twoElements = screen.getAllByText('2')
        expect(twoElements.length).toBeGreaterThan(0)
      })
    })

    it('displays running containers count', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const runningLabels = screen.getAllByText('Running')
        expect(runningLabels.length).toBeGreaterThan(0)
        // Should show 2 running (all tracked containers)
        const twoElements = screen.getAllByText('2')
        expect(twoElements.length).toBeGreaterThan(0)
      })
    })

    it('displays auto-update enabled count', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Auto-Update Enabled')).toBeInTheDocument()
        const oneElements = screen.getAllByText('1')
        expect(oneElements.length).toBeGreaterThan(0) // Only nginx has auto policy
      })
    })

    it('displays stale containers count', async () => {
      const staleUpdates = [
        { ...mockUpdates[0], reason_type: 'stale' },
      ]
      vi.mocked(api.updates.getAll).mockResolvedValue(staleUpdates)

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Stale Containers')).toBeInTheDocument()
      })
    })

    it('displays pending updates count', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Pending Updates')).toBeInTheDocument()
        const oneElements = screen.getAllByText('1')
        expect(oneElements.length).toBeGreaterThan(0)
      })
    })
  })

  describe('Analytics cards', () => {
    it('displays update frequency analytics', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Update Frequency')).toBeInTheDocument()
        expect(screen.getByText('10')).toBeInTheDocument() // total_updates
        const eightElements = screen.getAllByText('8')
        expect(eightElements.length).toBeGreaterThan(0) // successful
        const twoElements = screen.getAllByText('2')
        expect(twoElements.length).toBeGreaterThan(0) // failed
      })
    })

    it('shows average duration when available', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText(/Avg duration: 45s/)).toBeInTheDocument()
      })
    })

    it('shows "no analytics" message when no updates', async () => {
      vi.mocked(api.analytics.getSummary).mockResolvedValue({
        ...mockAnalytics,
        total_updates: 0,
      })

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText(/No analytics available yet/)).toBeInTheDocument()
      })
    })

    it('displays CVEs resolved when VulnForge enabled', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('CVEs Resolved')).toBeInTheDocument()
        expect(screen.getByText('15')).toBeInTheDocument()
      })
    })

    it('does not display CVEs card when VulnForge disabled', async () => {
      vi.mocked(api.settings.getAll).mockResolvedValue([
        { ...mockSettings[0], value: 'false' },
      ])

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.queryByText('CVEs Resolved')).not.toBeInTheDocument()
      })
    })

    it('displays policy distribution', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Policy Distribution')).toBeInTheDocument()
        const autoElements = screen.getAllByText('auto')
        expect(autoElements.length).toBeGreaterThan(0)
        const manualElements = screen.getAllByText('manual')
        expect(manualElements.length).toBeGreaterThan(0)
        const percentageElements = screen.getAllByText('1 (50%)')
        expect(percentageElements.length).toBe(2) // 1 auto, 1 manual = 50% each, appears twice
      })
    })
  })

  describe('Filtering', () => {
    it('filters containers by search term', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      const searchInput = screen.getByPlaceholderText('Search containers...')
      fireEvent.change(searchInput, { target: { value: 'nginx' } })

      const nginxElements = screen.getAllByText('nginx')
      expect(nginxElements.length).toBeGreaterThan(0)
      expect(screen.queryByText(/postgres/)).not.toBeInTheDocument()
    })

    it('filters by auto-update enabled', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      const autoUpdateSelect = screen.getByDisplayValue('All Auto-Update')
      fireEvent.change(autoUpdateSelect, { target: { value: 'enabled' } })

      const nginxElements = screen.getAllByText('nginx')
      expect(nginxElements.length).toBeGreaterThan(0)
      expect(screen.queryByText(/postgres/)).not.toBeInTheDocument()
    })

    it('filters by auto-update disabled', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const postgresElements = screen.getAllByText('postgres')
        expect(postgresElements.length).toBeGreaterThan(0)
      })

      const autoUpdateSelect = screen.getByDisplayValue('All Auto-Update')
      fireEvent.change(autoUpdateSelect, { target: { value: 'disabled' } })

      expect(screen.queryByText(/nginx/)).not.toBeInTheDocument()
      const postgresElements = screen.getAllByText('postgres')
      expect(postgresElements.length).toBeGreaterThan(0)
    })

    it('filters by has updates', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      const hasUpdateSelect = screen.getByDisplayValue('All Updates')
      fireEvent.change(hasUpdateSelect, { target: { value: 'yes' } })

      const nginxElements = screen.getAllByText('nginx')
      expect(nginxElements.length).toBeGreaterThan(0) // Has pending update
      expect(screen.queryByText(/postgres/)).not.toBeInTheDocument()
    })

    it('filters by no updates', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const postgresElements = screen.getAllByText('postgres')
        expect(postgresElements.length).toBeGreaterThan(0)
      })

      const hasUpdateSelect = screen.getByDisplayValue('All Updates')
      fireEvent.change(hasUpdateSelect, { target: { value: 'no' } })

      expect(screen.queryByText(/nginx/)).not.toBeInTheDocument()
      const postgresElements = screen.getAllByText('postgres')
      expect(postgresElements.length).toBeGreaterThan(0)
    })
  })

  describe('Action buttons', () => {
    it('renders Scan button', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Scan')).toBeInTheDocument()
      })
    })

    it('calls container sync on Scan button click', async () => {
      const { toast } = await import('sonner')
      vi.mocked(api.containers.sync).mockResolvedValue({
        message: 'Sync completed',
        success: true,
        containers_found: 5,
        stats: { added: 2, updated: 1, removed: 0, unchanged: 2 },
      })

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Scan')).toBeInTheDocument()
      })

      const scanButton = screen.getByText('Scan')
      fireEvent.click(scanButton)

      await waitFor(() => {
        expect(api.containers.sync).toHaveBeenCalledTimes(1)
        expect(toast.success).toHaveBeenCalledWith('Synced 5 containers: 2 added, 1 updated')
      })
    })

    it('shows scanning state during sync', async () => {
      vi.mocked(api.containers.sync).mockImplementation(() => new Promise(() => {})) // Never resolves

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Scan')).toBeInTheDocument()
      })

      const scanButton = screen.getByText('Scan')
      fireEvent.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('Scanning...')).toBeInTheDocument()
      })
    })

    it('renders Check Updates button', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Check Updates')).toBeInTheDocument()
      })
    })

    it('calls update check on Check Updates button click', async () => {
      const { toast } = await import('sonner')
      vi.mocked(api.updates.checkAll).mockResolvedValue({
        success: true,
        message: 'Check completed',
        stats: { checked: 10, updates_found: 3 },
      })

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Check Updates')).toBeInTheDocument()
      })

      const checkButton = screen.getByText('Check Updates')
      fireEvent.click(checkButton)

      await waitFor(() => {
        expect(api.updates.checkAll).toHaveBeenCalledTimes(1)
        expect(toast.success).toHaveBeenCalledWith('Checked 10 containers, found 3 updates')
      })
    })

    it('disables buttons during operations', async () => {
      vi.mocked(api.containers.sync).mockImplementation(() => new Promise(() => {}))

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('Scan')).toBeInTheDocument()
      })

      const scanButton = screen.getByText('Scan')
      const checkButton = screen.getByText('Check Updates')

      fireEvent.click(scanButton)

      await waitFor(() => {
        expect(scanButton).toBeDisabled()
        expect(checkButton).toBeDisabled()
      })
    })
  })

  describe('Container sections', () => {
    it('separates My Projects from Community Containers', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        // The "★ My Projects" text is split across span elements, so use regex
        expect(screen.getByText(/My Projects/)).toBeInTheDocument()
        expect(screen.getByText('Community Containers')).toBeInTheDocument()
      })
    })

    it('only shows My Projects section when no community containers', async () => {
      const myProjectsOnly = mockContainers.map(c => ({ ...c, is_my_project: true }))
      vi.mocked(api.containers.getAll).mockResolvedValue(myProjectsOnly)

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText(/My Projects/)).toBeInTheDocument()
        expect(screen.queryByText('Community Containers')).not.toBeInTheDocument()
      })
    })

    it('does not show section headers when only community containers', async () => {
      const communityOnly = mockContainers.map(c => ({ ...c, is_my_project: false }))
      vi.mocked(api.containers.getAll).mockResolvedValue(communityOnly)

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.queryByText('★ My Projects')).not.toBeInTheDocument()
        expect(screen.queryByText('Community Containers')).not.toBeInTheDocument()
      })
    })

    it('shows Update Available badge for containers with pending updates', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        // nginx has a pending update
        expect(screen.getByText(/Update Available/)).toBeInTheDocument()
      })
    })
  })

  describe('Empty states', () => {
    it('shows empty state when no containers', async () => {
      vi.mocked(api.containers.getAll).mockResolvedValue([])

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('No containers found')).toBeInTheDocument()
      })
    })

    it('shows empty state when all containers filtered out', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      const searchInput = screen.getByPlaceholderText('Search containers...')
      fireEvent.change(searchInput, { target: { value: 'nonexistent' } })

      await waitFor(() => {
        expect(screen.getByText('No containers found')).toBeInTheDocument()
      })
    })
  })

  describe('Container modal', () => {
    it('opens modal when container card is clicked', async () => {
      render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      // Click on the nginx container card - find the card by looking for the heading
      const { container } = render(<Dashboard />)
      await waitFor(() => {
        const headings = container.querySelectorAll('h3')
        const nginxHeading = Array.from(headings).find(h => h.textContent === 'nginx')
        expect(nginxHeading).toBeTruthy()
      })

      const headings = container.querySelectorAll('h3')
      const nginxHeading = Array.from(headings).find(h => h.textContent === 'nginx')
      const nginxCard = nginxHeading?.closest('.cursor-pointer') as HTMLElement
      fireEvent.click(nginxCard)

      await waitFor(() => {
        expect(screen.getByTestId('container-modal')).toBeInTheDocument()
        expect(screen.getByText('Modal for nginx')).toBeInTheDocument()
      })
    })

    it('closes modal when close button clicked', async () => {
      const { container } = render(<Dashboard />)

      await waitFor(() => {
        const nginxElements = screen.getAllByText('nginx')
        expect(nginxElements.length).toBeGreaterThan(0)
      })

      const headings = container.querySelectorAll('h3')
      const nginxHeading = Array.from(headings).find(h => h.textContent === 'nginx')
      const nginxCard = nginxHeading?.closest('.cursor-pointer') as HTMLElement
      fireEvent.click(nginxCard)

      await waitFor(() => {
        expect(screen.getByTestId('container-modal')).toBeInTheDocument()
      })

      const closeButton = screen.getByText('Close Modal')
      fireEvent.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByTestId('container-modal')).not.toBeInTheDocument()
      })
    })
  })

  describe('Edge cases', () => {
    it('handles null analytics gracefully', async () => {
      vi.mocked(api.analytics.getSummary).mockResolvedValue(null as unknown as AnalyticsSummary)

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText(/No analytics available yet/)).toBeInTheDocument()
      })
    })

    it('handles empty policy stats', async () => {
      vi.mocked(api.containers.getAll).mockResolvedValue([])

      render(<Dashboard />)

      await waitFor(() => {
        expect(screen.getByText('No containers found')).toBeInTheDocument()
      })
    })

    it('handles containers without policy field', async () => {
      const containersNullPolicy = mockContainers.map(c => ({ ...c, policy: '' as unknown as Container['policy'] }))
      vi.mocked(api.containers.getAll).mockResolvedValue(containersNullPolicy)

      render(<Dashboard />)

      await waitFor(() => {
        // Should default to 'manual' policy
        expect(screen.getByText('manual')).toBeInTheDocument()
      })
    })
  })
})
