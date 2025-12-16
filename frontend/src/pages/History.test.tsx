import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import History from './History'
import { api } from '../services/api'
import { UnifiedHistoryEvent } from '../types'

// Mock the API
vi.mock('../services/api', () => ({
  api: {
    history: {
      getAll: vi.fn(),
      rollback: vi.fn(),
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

// Mock StatusBadge component for simpler testing
vi.mock('../components/StatusBadge', () => ({
  default: ({ status }: { status: string }) => (
    <div data-testid={`status-badge-${status}`}>{status}</div>
  ),
}))

const mockUpdateHistory: UnifiedHistoryEvent[] = [
  {
    id: 1,
    event_type: 'update',
    container_id: 1,
    container_name: 'nginx',
    from_tag: '1.20.0',
    to_tag: '1.21.0',
    status: 'success',
    started_at: '2025-01-15T10:00:00Z',
    completed_at: '2025-01-15T10:02:30Z',
    performed_by: 'admin@test.com',
    rollback_available: true,
    error_message: null,
    trigger_reason: undefined,
    exit_code: undefined,
    duration_seconds: 150,
  },
  {
    id: 2,
    event_type: 'restart',
    container_id: 2,
    container_name: 'postgres',
    from_tag: undefined,
    to_tag: undefined,
    status: 'success',
    started_at: '2025-01-14T09:30:00Z',
    completed_at: '2025-01-14T09:30:15Z',
    performed_by: 'system',
    rollback_available: false,
    error_message: null,
    trigger_reason: 'health_check',
    exit_code: undefined,
    duration_seconds: 15,
  },
  {
    id: 3,
    event_type: 'update',
    container_id: 3,
    container_name: 'redis',
    from_tag: '6.2.0',
    to_tag: '6.2.6',
    status: 'failed',
    started_at: '2025-01-13T14:20:00Z',
    completed_at: '2025-01-13T14:21:00Z',
    performed_by: 'admin@test.com',
    rollback_available: false,
    error_message: 'Failed to pull image: timeout',
    trigger_reason: undefined,
    exit_code: undefined,
    duration_seconds: 60,
  },
  {
    id: 4,
    event_type: 'restart',
    container_id: 4,
    container_name: 'mysql',
    from_tag: undefined,
    to_tag: undefined,
    status: 'success',
    started_at: '2025-01-12T08:00:00Z',
    completed_at: '2025-01-12T08:00:45Z',
    performed_by: 'admin@test.com',
    rollback_available: false,
    error_message: null,
    trigger_reason: 'manual: Database migration restart',
    exit_code: undefined,
    duration_seconds: 45,
  },
  {
    id: 5,
    event_type: 'restart',
    container_id: 5,
    container_name: 'mongo',
    from_tag: undefined,
    to_tag: undefined,
    status: 'failed',
    started_at: '2025-01-11T16:45:00Z',
    completed_at: '2025-01-11T16:46:00Z',
    performed_by: 'system',
    rollback_available: false,
    error_message: 'Container failed to start: port already in use',
    trigger_reason: 'exit_code',
    exit_code: 1,
    duration_seconds: 60,
  },
  {
    id: 6,
    event_type: 'update',
    container_id: 6,
    container_name: 'rabbitmq',
    from_tag: '3.8.0',
    to_tag: '3.9.0',
    status: 'success',
    started_at: '2025-01-10T12:00:00Z',
    completed_at: null, // In progress
    performed_by: 'admin@test.com',
    rollback_available: false,
    error_message: null,
    trigger_reason: undefined,
    exit_code: undefined,
    duration_seconds: null,
  },
]

describe('History', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(mockUpdateHistory)
  })

  describe('Data loading', () => {
    it('loads history on mount', async () => {
      render(<History />)

      await waitFor(() => {
        expect(api.history.getAll).toHaveBeenCalledTimes(1)
      })
    })

    it('shows loading state while fetching', () => {
      render(<History />)

      expect(screen.getByText('Loading history...')).toBeInTheDocument()
    })

    it('displays history after loading', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('postgres')).toBeInTheDocument()
      expect(screen.getByText('redis')).toBeInTheDocument()
    })

    it('handles API error gracefully', async () => {
      const { toast } = await import('sonner')
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<History />)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to load history')
      })
    })
  })

  describe('Header and controls', () => {
    it('renders page title and description', () => {
      render(<History />)

      expect(screen.getByText('History')).toBeInTheDocument()
      expect(screen.getByText('View container updates and restart events')).toBeInTheDocument()
    })

    it('renders refresh button', async () => {
      render(<History />)

      await waitFor(() => {
        const refreshButtons = screen.getAllByText('Refresh')
        expect(refreshButtons.length).toBeGreaterThan(0)
      })
    })

    it('refreshes data when refresh button clicked', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const refreshButtons = screen.getAllByText('Refresh')
      fireEvent.click(refreshButtons[0])

      await waitFor(() => {
        expect(api.history.getAll).toHaveBeenCalledTimes(2) // Initial load + refresh
      })
    })

    it('disables refresh button while loading', () => {
      render(<History />)

      const refreshButtons = screen.getAllByText('Refresh')
      expect(refreshButtons[0]).toBeDisabled()
    })
  })

  describe('History table', () => {
    it('renders table headers', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('Container')).toBeInTheDocument()
      expect(screen.getByText('Event')).toBeInTheDocument()
      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('Started')).toBeInTheDocument()
      expect(screen.getByText('Duration')).toBeInTheDocument()
      expect(screen.getByText('Performed By')).toBeInTheDocument()
      expect(screen.getByText('Actions')).toBeInTheDocument()
    })

    it('displays container names', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('postgres')).toBeInTheDocument()
      expect(screen.getByText('redis')).toBeInTheDocument()
      expect(screen.getByText('mysql')).toBeInTheDocument()
      expect(screen.getByText('mongo')).toBeInTheDocument()
      expect(screen.getByText('rabbitmq')).toBeInTheDocument()
    })

    it('displays status badges', async () => {
      const { container } = render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // Check for status badges
      const successBadges = container.querySelectorAll('[data-testid="status-badge-success"]')
      expect(successBadges.length).toBeGreaterThan(0)

      const failedBadges = container.querySelectorAll('[data-testid="status-badge-failed"]')
      expect(failedBadges.length).toBeGreaterThan(0)
    })

    it('displays performed by information', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const adminElements = screen.getAllByText('admin@test.com')
      expect(adminElements.length).toBeGreaterThan(0)

      const systemElements = screen.getAllByText(/System|system/)
      expect(systemElements.length).toBeGreaterThan(0)
    })
  })

  describe('Update events', () => {
    it('displays version transitions for updates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // nginx update: 1.20.0 → 1.21.0
      expect(screen.getByText('1.20.0')).toBeInTheDocument()
      expect(screen.getByText('1.21.0')).toBeInTheDocument()

      // redis update: 6.2.0 → 6.2.6
      expect(screen.getByText('6.2.0')).toBeInTheDocument()
      expect(screen.getByText('6.2.6')).toBeInTheDocument()
    })

    it('shows rollback button for rollbackable updates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      expect(rollbackButtons.length).toBeGreaterThan(0)
    })

    it('does not show rollback for non-rollbackable updates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // Only nginx (id=1) has rollback_available=true
      const rollbackButtons = screen.getAllByText('Rollback')
      expect(rollbackButtons.length).toBe(1)
    })

    it('shows duration for completed updates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // nginx update took 150 seconds (10:00:00 to 10:02:30)
      const duration = screen.getByText('150s')
      expect(duration).toBeInTheDocument()
    })

    it('shows "In progress" for ongoing updates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // rabbitmq update has no completed_at
      const inProgress = screen.getByText('In progress')
      expect(inProgress).toBeInTheDocument()
    })
  })

  describe('Restart events', () => {
    it('displays trigger reason for health check', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('Health Check Failed')).toBeInTheDocument()
    })

    it('displays trigger reason for exit code', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('Container Exited')).toBeInTheDocument()
    })

    it('displays exit code when available', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // mongo restart has exit_code: 1
      expect(screen.getByText('(exit 1)')).toBeInTheDocument()
    })

    it('displays manual restart reason', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // mysql restart has manual reason
      expect(screen.getByText('Database migration restart')).toBeInTheDocument()
    })

    it('does not show rollback for restart events', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // Only 1 rollback button (for nginx update), not for restart events
      const rollbackButtons = screen.getAllByText('Rollback')
      expect(rollbackButtons.length).toBe(1)
    })
  })

  describe('Rollback functionality', () => {
    it('shows confirmation before rollback', async () => {
      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => false)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      fireEvent.click(rollbackButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalledWith(
          'Are you sure you want to rollback this update? This will restore the previous version.'
        )
      })

      window.confirm = originalConfirm
    })

    it('calls rollback API when confirmed', async () => {
      const { toast } = await import('sonner')
      ;(api.history.rollback as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      fireEvent.click(rollbackButtons[0])

      await waitFor(() => {
        expect(api.history.rollback).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Rollback initiated successfully')
      })

      window.confirm = originalConfirm
    })

    it('does not call rollback when cancelled', async () => {
      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => false)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      fireEvent.click(rollbackButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled()
      })

      expect(api.history.rollback).not.toHaveBeenCalled()

      window.confirm = originalConfirm
    })

    it('reloads history after successful rollback', async () => {
      ;(api.history.rollback as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      fireEvent.click(rollbackButtons[0])

      await waitFor(() => {
        expect(api.history.getAll).toHaveBeenCalledTimes(2) // Initial load + reload
      })

      window.confirm = originalConfirm
    })

    it('handles rollback error', async () => {
      const { toast } = await import('sonner')
      ;(api.history.rollback as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const rollbackButtons = screen.getAllByText('Rollback')
      fireEvent.click(rollbackButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to rollback update')
      })

      window.confirm = originalConfirm
    })
  })

  describe('Error messages section', () => {
    it('displays error messages section when errors exist', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText('Recent Errors')).toBeInTheDocument()
    })

    it('shows error details for failed events', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // redis failed update
      expect(screen.getByText('Failed to pull image: timeout')).toBeInTheDocument()

      // mongo failed restart
      expect(screen.getByText('Container failed to start: port already in use')).toBeInTheDocument()
    })

    it('displays container name and event type in error', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.getByText(/redis \(update\)/)).toBeInTheDocument()
      expect(screen.getByText(/mongo \(restart\)/)).toBeInTheDocument()
    })

    it('limits error display to 5 recent errors', async () => {
      // Create history with 7 errors
      const manyErrors = Array.from({ length: 7 }, (_, i) => ({
        id: i + 100,
        event_type: 'update' as const,
        container_id: i + 100,
        container_name: `container-${i}`,
        from_tag: '1.0.0',
        to_tag: '2.0.0',
        status: 'failed',
        started_at: `2025-01-0${i + 1}T10:00:00Z`,
        completed_at: `2025-01-0${i + 1}T10:01:00Z`,
        performed_by: 'admin',
        rollback_available: false,
        error_message: `Error ${i + 1}`,
        trigger_reason: null,
        exit_code: null,
      }))

      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(manyErrors)

      const { container } = render(<History />)

      await waitFor(() => {
        expect(screen.getByText('Recent Errors')).toBeInTheDocument()
      })

      // Should only show 5 errors
      const errorDivs = container.querySelectorAll('.bg-red-500\\/10')
      expect(errorDivs.length).toBe(5)
    })

    it('does not show errors section when no errors exist', async () => {
      const noErrors = mockUpdateHistory.filter((h) => !h.error_message)
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(noErrors)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      expect(screen.queryByText('Recent Errors')).not.toBeInTheDocument()
    })
  })

  describe('Empty state', () => {
    it('shows empty state when no history available', async () => {
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue([])

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('No history found')).toBeInTheDocument()
      })

      expect(screen.getByText('Container updates and restarts will appear here')).toBeInTheDocument()
    })
  })

  describe('Date formatting', () => {
    it('displays formatted dates', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // Check for date format (allowing for timezone variations) - multiple dates exist
      const dateElements = screen.getAllByText(/Jan 1[0-5], 2025/)
      expect(dateElements.length).toBeGreaterThan(0)
    })

    it('displays formatted times', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // Times are displayed in HH:mm:ss format
      const times = screen.getAllByText(/\d{2}:\d{2}:\d{2}/)
      expect(times.length).toBeGreaterThan(0)
    })
  })

  describe('Edge cases', () => {
    it('handles events without performed_by as System', async () => {
      const noPerformer = [
        {
          ...mockUpdateHistory[0],
          performed_by: null,
        },
      ]
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(noPerformer)

      render(<History />)

      await waitFor(() => {
        const systemElements = screen.getAllByText(/System|system/)
        expect(systemElements.length).toBeGreaterThan(0)
      })
    })

    it('handles unknown trigger reasons', async () => {
      const unknownReason = [
        {
          ...mockUpdateHistory[1],
          trigger_reason: 'unknown_reason_type',
        },
      ]
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(unknownReason)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })

      // Unknown reasons get underscores replaced with spaces
      expect(screen.getByText('unknown reason type')).toBeInTheDocument()
    })

    it('handles missing trigger reason', async () => {
      const noReason = [
        {
          ...mockUpdateHistory[1],
          trigger_reason: null,
        },
      ]
      ;(api.history.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(noReason)

      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })

      expect(screen.getByText('Unknown')).toBeInTheDocument()
    })

    it('handles null exit code gracefully', async () => {
      render(<History />)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      // postgres has null exit_code, should not show exit code
      const postgresRow = screen.getByText('postgres').closest('tr')
      expect(postgresRow?.textContent).not.toContain('exit')
    })
  })
})
