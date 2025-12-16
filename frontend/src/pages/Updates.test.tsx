import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Updates from './Updates'
import { api } from '../services/api'

// Mock the API
vi.mock('../services/api', () => ({
  api: {
    updates: {
      getAll: vi.fn(),
      getSecurity: vi.fn(),
      get: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      apply: vi.fn(),
      snooze: vi.fn(),
      removeContainer: vi.fn(),
      cancelRetry: vi.fn(),
      delete: vi.fn(),
      checkAll: vi.fn(),
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

// Mock UpdateCard component for simpler testing
interface UpdateCardProps {
  update: {
    id: number;
    container_name: string;
    status: string;
    current_version?: string;
    available_version?: string;
    cves_fixed?: string[];
  };
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onApply: (id: number) => void;
  onSnooze: (id: number) => void;
  onRemoveContainer: (id: number) => void;
  onCancelRetry: (id: number) => void;
  onDelete: (id: number) => void;
  isApplying?: boolean;
}

vi.mock('../components/UpdateCard', () => ({
  default: ({ update, onApprove, onReject, onApply, onSnooze, onRemoveContainer, onCancelRetry, onDelete, isApplying }: UpdateCardProps) => (
    <div data-testid={`update-card-${update.id}`}>
      <div>Update for {update.container_name}</div>
      <div>Status: {update.status}</div>
      <div>From: {update.current_version}</div>
      <div>To: {update.available_version}</div>
      {update.cves_fixed && update.cves_fixed.length > 0 && (
        <div>Security: {update.cves_fixed.length} CVEs</div>
      )}
      {isApplying && <div>Applying...</div>}
      <button onClick={() => onApprove(update.id)}>Approve</button>
      <button onClick={() => onReject(update.id)}>Reject</button>
      <button onClick={() => onApply(update.id)}>Apply</button>
      <button onClick={() => onSnooze(update.id)}>Snooze</button>
      <button onClick={() => onRemoveContainer(update.id)}>Remove Container</button>
      <button onClick={() => onCancelRetry(update.id)}>Cancel Retry</button>
      <button onClick={() => onDelete(update.id)}>Delete</button>
    </div>
  ),
}))

const mockUpdates = [
  {
    id: 1,
    container_id: 1,
    container_name: 'nginx',
    current_version: '1.20.0',
    available_version: '1.21.0',
    status: 'pending',
    reason_type: 'minor',
    cves_fixed: [],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 2,
    container_id: 2,
    container_name: 'postgres',
    current_version: '13.5',
    available_version: '14.0',
    status: 'approved',
    reason_type: 'major',
    cves_fixed: [],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 3,
    container_id: 3,
    container_name: 'redis',
    current_version: '6.2.0',
    available_version: '6.2.6',
    status: 'rejected',
    reason_type: 'patch',
    cves_fixed: [],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 4,
    container_id: 4,
    container_name: 'mysql',
    current_version: '8.0.0',
    available_version: '8.0.5',
    status: 'applied',
    reason_type: 'security',
    cves_fixed: ['CVE-2025-1234', 'CVE-2025-5678'],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 5,
    container_id: 5,
    container_name: 'mongo',
    current_version: '4.4.0',
    available_version: '5.0.0',
    status: 'pending',
    reason_type: 'stale',
    cves_fixed: [],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 6,
    container_id: 6,
    container_name: 'rabbitmq',
    current_version: '3.8.0',
    available_version: '3.9.0',
    status: 'pending_retry',
    reason_type: 'minor',
    cves_fixed: [],
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 7,
    container_id: 7,
    container_name: 'apache',
    current_version: '2.4.48',
    available_version: '2.4.50',
    status: 'pending',
    reason_type: 'security',
    cves_fixed: ['CVE-2025-9999'],
    created_at: '2025-01-01T00:00:00Z',
  },
]

describe('Updates', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.updates.getAll as ReturnType<typeof vi.fn>).mockResolvedValue(mockUpdates)
    ;(api.updates.getSecurity as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockUpdates.filter((u) => u.cves_fixed && u.cves_fixed.length > 0)
    )
  })

  describe('Data loading', () => {
    it('loads updates on mount', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(api.updates.getAll).toHaveBeenCalledTimes(1)
      })
    })

    it('shows loading state while fetching', () => {
      render(<Updates />)

      const loadingText = screen.getByText('Loading updates...')
      expect(loadingText).toBeInTheDocument()
    })

    it('displays updates after loading', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      expect(screen.getByText(/Update for postgres/)).toBeInTheDocument()
      expect(screen.getByText(/Update for redis/)).toBeInTheDocument()
    })

    it('handles API error gracefully', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.getAll as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<Updates />)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to load updates')
      })
    })
  })

  describe('Statistics display', () => {
    it('displays pending count', async () => {
      render(<Updates />)

      await waitFor(() => {
        const pendingLabels = screen.getAllByText('Pending')
        expect(pendingLabels.length).toBeGreaterThan(0)
      })

      // 3 pending updates (nginx, mongo, apache)
      const threeElements = screen.getAllByText('3')
      expect(threeElements.length).toBeGreaterThan(0)
    })

    it('displays approved count', async () => {
      render(<Updates />)

      await waitFor(() => {
        const approvedLabels = screen.getAllByText('Approved')
        expect(approvedLabels.length).toBeGreaterThan(0)
      })

      // 1 approved update (postgres)
      const oneElements = screen.getAllByText('1')
      expect(oneElements.length).toBeGreaterThan(0)
    })

    it('displays rejected count', async () => {
      render(<Updates />)

      await waitFor(() => {
        const rejectedLabels = screen.getAllByText('Rejected')
        expect(rejectedLabels.length).toBeGreaterThan(0)
      })

      // 1 rejected update (redis)
      const oneElements = screen.getAllByText('1')
      expect(oneElements.length).toBeGreaterThan(0)
    })

    it('displays stale count', async () => {
      render(<Updates />)

      await waitFor(() => {
        const staleLabels = screen.getAllByText('Stale')
        expect(staleLabels.length).toBeGreaterThan(0)
      })

      // 1 stale update (mongo)
      const oneElements = screen.getAllByText('1')
      expect(oneElements.length).toBeGreaterThan(0)
    })

    it('displays applied count', async () => {
      render(<Updates />)

      await waitFor(() => {
        const appliedLabels = screen.getAllByText('Applied')
        expect(appliedLabels.length).toBeGreaterThan(0)
      })

      // 1 applied update (mysql)
      const oneElements = screen.getAllByText('1')
      expect(oneElements.length).toBeGreaterThan(0)
    })

    it('displays security count from allUpdates', async () => {
      render(<Updates />)

      await waitFor(() => {
        // Security count shows 2 (mysql and apache)
        expect(screen.getByText(/Security \(2\)/)).toBeInTheDocument()
      })
    })
  })

  describe('Filter type switching', () => {
    it('shows all updates by default', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      expect(screen.getByText(/Update for postgres/)).toBeInTheDocument()
    })

    it('switches to security updates filter', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const securityButton = screen.getByText(/Security \(2\)/)
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(api.updates.getSecurity).toHaveBeenCalled()
      })
    })

    it('highlights active filter type button', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const allButton = screen.getByText('All Updates')
      expect(allButton).toHaveClass('bg-primary')

      const securityButton = screen.getByText(/Security \(2\)/)
      fireEvent.click(securityButton)

      await waitFor(() => {
        expect(securityButton).toHaveClass('bg-primary')
      })
    })
  })

  describe('Status filtering', () => {
    it('shows all non-applied updates by default', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      // All updates except mysql (which is applied)
      expect(screen.getByText(/Update for postgres/)).toBeInTheDocument()
      expect(screen.getByText(/Update for redis/)).toBeInTheDocument()
      expect(screen.queryByText(/Update for mysql/)).not.toBeInTheDocument()
    })

    it('filters to pending updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const pendingButton = screen.getByText(/Pending \(3\)/)
      fireEvent.click(pendingButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      expect(screen.getByText(/Update for mongo/)).toBeInTheDocument()
      expect(screen.getByText(/Update for apache/)).toBeInTheDocument()
      expect(screen.queryByText(/Update for postgres/)).not.toBeInTheDocument()
    })

    it('filters to approved updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const approvedButton = screen.getByText(/Approved \(1\)/)
      fireEvent.click(approvedButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for postgres/)).toBeInTheDocument()
      })

      expect(screen.queryByText(/Update for nginx/)).not.toBeInTheDocument()
    })

    it('filters to rejected updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const rejectedButton = screen.getByText(/Rejected \(1\)/)
      fireEvent.click(rejectedButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for redis/)).toBeInTheDocument()
      })

      expect(screen.queryByText(/Update for nginx/)).not.toBeInTheDocument()
    })

    it('filters to stale updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const staleButton = screen.getByText(/Stale \(1\)/)
      fireEvent.click(staleButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for mongo/)).toBeInTheDocument()
      })

      expect(screen.queryByText(/Update for nginx/)).not.toBeInTheDocument()
    })

    it('filters to retrying updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const retryingButton = screen.getByText(/Retrying \(1\)/)
      fireEvent.click(retryingButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for rabbitmq/)).toBeInTheDocument()
      })

      expect(screen.queryByText(/Update for nginx/)).not.toBeInTheDocument()
    })

    it('filters to applied updates only', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const appliedButton = screen.getByText(/Applied \(1\)/)
      fireEvent.click(appliedButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for mysql/)).toBeInTheDocument()
      })

      expect(screen.queryByText(/Update for nginx/)).not.toBeInTheDocument()
    })

    it('highlights active filter button', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const pendingButton = screen.getByText(/Pending \(3\)/)
      fireEvent.click(pendingButton)

      await waitFor(() => {
        expect(pendingButton).toHaveClass('bg-primary')
      })
    })
  })

  describe('Check all action', () => {
    it('calls checkAll API when button clicked', async () => {
      ;(api.updates.checkAll as ReturnType<typeof vi.fn>).mockResolvedValue({
        stats: { checked: 10, updates_found: 5 },
      })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const checkAllButtons = screen.getAllByText('Check All')
      fireEvent.click(checkAllButtons[0])

      await waitFor(() => {
        expect(api.updates.checkAll).toHaveBeenCalled()
      })
    })

    it('shows success toast with stats after checking', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.checkAll as ReturnType<typeof vi.fn>).mockResolvedValue({
        stats: { checked: 10, updates_found: 5 },
      })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const checkAllButtons = screen.getAllByText('Check All')
      fireEvent.click(checkAllButtons[0])

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Checked 10 containers, found 5 updates')
      })
    })

    it('reloads updates after checking', async () => {
      ;(api.updates.checkAll as ReturnType<typeof vi.fn>).mockResolvedValue({
        stats: { checked: 10, updates_found: 5 },
      })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const checkAllButtons = screen.getAllByText('Check All')
      fireEvent.click(checkAllButtons[0])

      await waitFor(() => {
        expect(api.updates.getAll).toHaveBeenCalledTimes(2) // Initial load + reload
      })
    })

    it('handles check all error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.checkAll as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const checkAllButtons = screen.getAllByText('Check All')
      fireEvent.click(checkAllButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to check for updates')
      })
    })

    it('disables check all button while loading', async () => {
      render(<Updates />)

      const checkAllButtons = screen.getAllByText('Check All')
      expect(checkAllButtons[0]).toBeDisabled()
    })
  })

  describe('Update actions', () => {
    it('approves update when approve action called', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.approve as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const approveButtons = screen.getAllByText('Approve')
      fireEvent.click(approveButtons[0])

      await waitFor(() => {
        expect(api.updates.approve).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Update approved')
      })
    })

    it('rejects update with reason when reject action called', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.reject as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      // Mock window.prompt
      const originalPrompt = window.prompt
      window.prompt = vi.fn(() => 'Test rejection reason')

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const rejectButtons = screen.getAllByText('Reject')
      fireEvent.click(rejectButtons[0])

      await waitFor(() => {
        expect(window.prompt).toHaveBeenCalledWith('Reason for rejection (optional):')
        expect(api.updates.reject).toHaveBeenCalledWith(1, 'Test rejection reason')
        expect(toast.success).toHaveBeenCalledWith('Update rejected')
      })

      window.prompt = originalPrompt
    })

    it('rejects update without reason when prompt cancelled', async () => {
      await import('sonner')
      ;(api.updates.reject as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      // Mock window.prompt to return null (cancelled)
      const originalPrompt = window.prompt
      window.prompt = vi.fn(() => null)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const rejectButtons = screen.getAllByText('Reject')
      fireEvent.click(rejectButtons[0])

      await waitFor(() => {
        expect(api.updates.reject).toHaveBeenCalledWith(1, undefined)
      })

      window.prompt = originalPrompt
    })

    it('applies update with confirmation when apply action called', async () => {
      await import('sonner')
      ;(api.updates.apply as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })
      ;(api.updates.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        id: 1,
        status: 'applied',
      })

      // Mock window.confirm
      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const applyButtons = screen.getAllByText('Apply')
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalledWith('Are you sure you want to apply this update?')
        expect(api.updates.apply).toHaveBeenCalledWith(1)
      })

      window.confirm = originalConfirm
    })

    it('does not apply update when confirmation cancelled', async () => {
      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => false)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const applyButtons = screen.getAllByText('Apply')
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled()
      })

      expect(api.updates.apply).not.toHaveBeenCalled()

      window.confirm = originalConfirm
    })

    it('shows applying state during update application', async () => {
      ;(api.updates.apply as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(resolve => setTimeout(resolve, 100)))
      ;(api.updates.get as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 1, status: 'applied' })

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const applyButtons = screen.getAllByText('Apply')
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        expect(screen.getByText('Applying...')).toBeInTheDocument()
      })

      window.confirm = originalConfirm
    })

    it('snoozes notification when snooze action called', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.snooze as ReturnType<typeof vi.fn>).mockResolvedValue({ message: 'Notification snoozed' })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const snoozeButtons = screen.getAllByText('Snooze')
      fireEvent.click(snoozeButtons[0])

      await waitFor(() => {
        expect(api.updates.snooze).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Notification snoozed')
      })
    })

    it('removes container with confirmation', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.removeContainer as ReturnType<typeof vi.fn>).mockResolvedValue({ message: 'Container removed' })

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const removeButtons = screen.getAllByText('Remove Container')
      fireEvent.click(removeButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalledWith(
          'Are you sure you want to permanently remove this container from the database? This action cannot be undone.'
        )
        expect(api.updates.removeContainer).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Container removed')
      })

      window.confirm = originalConfirm
    })

    it('cancels retry when cancel retry action called', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.cancelRetry as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const cancelButtons = screen.getAllByText('Cancel Retry')
      fireEvent.click(cancelButtons[0])

      await waitFor(() => {
        expect(api.updates.cancelRetry).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Retry cancelled, update reset to pending')
      })
    })

    it('deletes update with confirmation', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ message: 'Update deleted' })

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const deleteButtons = screen.getAllByText('Delete')
      fireEvent.click(deleteButtons[0])

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalledWith(
          'Are you sure you want to delete this update? This action cannot be undone.'
        )
        expect(api.updates.delete).toHaveBeenCalledWith(1)
        expect(toast.success).toHaveBeenCalledWith('Update deleted')
      })

      window.confirm = originalConfirm
    })
  })

  describe('Error handling', () => {
    it('handles approve error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.approve as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const approveButtons = screen.getAllByText('Approve')
      fireEvent.click(approveButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('API Error')
      })
    })

    it('handles reject error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.reject as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      const originalPrompt = window.prompt
      window.prompt = vi.fn(() => 'Test reason')

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const rejectButtons = screen.getAllByText('Reject')
      fireEvent.click(rejectButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('API Error')
      })

      window.prompt = originalPrompt
    })

    it('handles apply error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.apply as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const applyButtons = screen.getAllByText('Apply')
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        // The error message from the Error object is passed through
        expect(toast.error).toHaveBeenCalledWith('API Error')
      })

      window.confirm = originalConfirm
    })

    it('handles snooze error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.snooze as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const snoozeButtons = screen.getAllByText('Snooze')
      fireEvent.click(snoozeButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to snooze notification')
      })
    })

    it('handles remove container error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.removeContainer as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const removeButtons = screen.getAllByText('Remove Container')
      fireEvent.click(removeButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to remove container')
      })

      window.confirm = originalConfirm
    })

    it('handles cancel retry error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.cancelRetry as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const cancelButtons = screen.getAllByText('Cancel Retry')
      fireEvent.click(cancelButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to cancel retry')
      })
    })

    it('handles delete error', async () => {
      const { toast } = await import('sonner')
      ;(api.updates.delete as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API Error'))

      const originalConfirm = window.confirm
      window.confirm = vi.fn(() => true)

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      const deleteButtons = screen.getAllByText('Delete')
      fireEvent.click(deleteButtons[0])

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Failed to delete update')
      })

      window.confirm = originalConfirm
    })
  })

  describe('Empty state', () => {
    it('shows empty state when no updates available', async () => {
      ;(api.updates.getAll as ReturnType<typeof vi.fn>).mockResolvedValue([])

      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText('No updates found')).toBeInTheDocument()
      })
    })

    it('shows check for updates button in empty state', async () => {
      ;(api.updates.getAll as ReturnType<typeof vi.fn>).mockResolvedValue([])

      render(<Updates />)

      await waitFor(() => {
        const checkButtons = screen.getAllByText('Check for Updates')
        expect(checkButtons.length).toBeGreaterThan(0)
      })
    })

    it('shows empty state when filter has no matches', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      // Filter to a status with no updates
      const rejectedButton = screen.getByText(/Rejected \(1\)/)
      fireEvent.click(rejectedButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for redis/)).toBeInTheDocument()
      })

      // Then filter to security which should have no rejected updates
      const securityButton = screen.getByText(/Security \(2\)/)
      fireEvent.click(securityButton)

      await waitFor(() => {
        // After switching to security view with rejected filter, should show empty
        expect(api.updates.getSecurity).toHaveBeenCalled()
      })
    })
  })

  describe('Edge cases', () => {
    it('handles updates with no CVEs', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      // nginx update has no CVEs, should render without security info
      const nginxCard = screen.getByTestId('update-card-1')
      expect(nginxCard).toBeInTheDocument()
      expect(nginxCard.textContent).not.toContain('Security:')
    })

    it('handles updates with CVEs', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Update for nginx/)).toBeInTheDocument()
      })

      // Switch to applied filter to see mysql update (which has CVEs)
      const appliedButton = screen.getByText(/Applied \(1\)/)
      fireEvent.click(appliedButton)

      await waitFor(() => {
        expect(screen.getByText(/Update for mysql/)).toBeInTheDocument()
      })

      // mysql update has 2 CVEs
      const mysqlCard = screen.getByTestId('update-card-4')
      expect(mysqlCard.textContent).toContain('Security: 2 CVEs')
    })

    it('maintains security count across filter switches', async () => {
      render(<Updates />)

      await waitFor(() => {
        expect(screen.getByText(/Security \(2\)/)).toBeInTheDocument()
      })

      // Switch to pending filter
      const pendingButton = screen.getByText(/Pending \(3\)/)
      fireEvent.click(pendingButton)

      await waitFor(() => {
        // Security count should still be 2
        expect(screen.getByText(/Security \(2\)/)).toBeInTheDocument()
      })
    })
  })
})
