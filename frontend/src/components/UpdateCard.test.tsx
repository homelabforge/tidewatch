import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import UpdateCard from './UpdateCard'
import { mockUpdate } from '../__tests__/mockData'

describe('UpdateCard', () => {
  const defaultUpdate = {
    ...mockUpdate,
    registry: 'docker.io',
    reason_type: 'feature',
    reason_summary: 'New features and improvements',
    recommendation: 'Recommended',
    changelog: null,
    changelog_url: null,
    cves_fixed: [],
    current_vulns: 0,
    new_vulns: 0,
    vuln_delta: 0,
    published_date: '2025-01-01T00:00:00Z',
    image_size_delta: 0,
    approved_by: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    rejection_reason: null,
    retry_count: 0,
    max_retries: 3,
    next_retry_at: null,
    last_error: null,
    backoff_multiplier: 3,
    snoozed_until: null,
  }

  describe('Basic rendering', () => {
    it('renders container name', () => {
      render(<UpdateCard update={defaultUpdate} />)
      expect(screen.getByText('nginx')).toBeInTheDocument()
    })

    it('renders version information', () => {
      render(<UpdateCard update={defaultUpdate} />)
      expect(screen.getByText('1.20')).toBeInTheDocument()
      expect(screen.getByText('1.21')).toBeInTheDocument()
    })

    it('renders status badge', () => {
      render(<UpdateCard update={defaultUpdate} />)
      expect(screen.getByText('Pending')).toBeInTheDocument()
    })

    it('renders update reason', () => {
      render(<UpdateCard update={defaultUpdate} />)
      expect(screen.getByText('feature Update')).toBeInTheDocument()
      expect(screen.getByText('New features and improvements')).toBeInTheDocument()
    })
  })

  describe('Stale updates', () => {
    const staleUpdate = { ...defaultUpdate, reason_type: 'stale' }

    it('shows inactive container message for stale updates', () => {
      render(<UpdateCard update={staleUpdate} />)
      expect(screen.getByText('• Inactive Container')).toBeInTheDocument()
    })

    it('applies orange border for stale updates', () => {
      const { container } = render(<UpdateCard update={staleUpdate} />)
      const card = container.querySelector('.border-orange-600')
      expect(card).toBeInTheDocument()
    })

    it('shows stale-specific actions', () => {
      const onSnooze = vi.fn()
      const onRemoveContainer = vi.fn()
      const onReject = vi.fn()

      render(<UpdateCard update={staleUpdate} onSnooze={onSnooze} onRemoveContainer={onRemoveContainer} onReject={onReject} />)

      expect(screen.getByText('Snooze')).toBeInTheDocument()
      expect(screen.getByText('Remove')).toBeInTheDocument()
      expect(screen.getByText('Keep')).toBeInTheDocument()
    })
  })

  describe('Security information', () => {
    it('displays CVEs fixed count', () => {
      const securityUpdate = {
        ...defaultUpdate,
        reason_type: 'security',
        cves_fixed: ['CVE-2025-1234', 'CVE-2025-5678'],
      }

      render(<UpdateCard update={securityUpdate} />)
      expect(screen.getByText(/Fixes 2 CVEs/)).toBeInTheDocument()
    })

    it('displays vulnerability delta decrease', () => {
      const update = { ...defaultUpdate, vuln_delta: -5 }

      render(<UpdateCard update={update} />)
      expect(screen.getByText(/↓ 5 vulnerabilities/)).toBeInTheDocument()
    })

    it('displays vulnerability delta increase', () => {
      const update = { ...defaultUpdate, vuln_delta: 3 }

      render(<UpdateCard update={update} />)
      expect(screen.getByText(/↑ 3 vulnerabilities/)).toBeInTheDocument()
    })
  })

  describe('Recommendations', () => {
    it('renders "Highly recommended" in green', () => {
      const update = { ...defaultUpdate, recommendation: 'Highly recommended' }

      render(<UpdateCard update={update} />)
      const rec = screen.getByText('Highly recommended')
      expect(rec).toHaveClass('text-green-400')
    })

    it('renders "Optional" in blue', () => {
      const update = { ...defaultUpdate, recommendation: 'Optional' }

      render(<UpdateCard update={update} />)
      const rec = screen.getByText('Optional')
      expect(rec).toHaveClass('text-blue-400')
    })

    it('renders "Review required" in yellow', () => {
      const update = { ...defaultUpdate, recommendation: 'Review required' }

      render(<UpdateCard update={update} />)
      const rec = screen.getByText('Review required')
      expect(rec).toHaveClass('text-yellow-400')
    })
  })

  describe('Changelog', () => {
    it('shows changelog toggle button when changelog exists', () => {
      const update = { ...defaultUpdate, changelog: '## Release Notes\n\nNew features added' }

      render(<UpdateCard update={update} />)
      expect(screen.getByText('Release Notes')).toBeInTheDocument()
    })

    it('toggles changelog visibility', async () => {
      const update = { ...defaultUpdate, changelog: '## Release Notes\n\nNew features added' }

      render(<UpdateCard update={update} />)

      const toggleButton = screen.getByText('Release Notes')
      fireEvent.click(toggleButton)

      await waitFor(() => {
        expect(screen.getByText(/New features added/)).toBeInTheDocument()
      })
    })

    it('shows external changelog link when URL provided', () => {
      const update = { ...defaultUpdate, changelog_url: 'https://github.com/example/releases' }

      render(<UpdateCard update={update} />)
      expect(screen.getByText('View Release Notes')).toBeInTheDocument()
    })
  })

  describe('Metadata', () => {
    it('displays published date', () => {
      render(<UpdateCard update={defaultUpdate} />)
      // The date-fns format is 'MMM d, yyyy'
      // Note: Date parsing can vary by timezone, so we check for the format pattern
      expect(screen.getByText(/Published:/)).toBeInTheDocument()
      expect(screen.getByText(/Published: (Dec 31, 2024|Jan 1, 2025)/)).toBeInTheDocument()
    })

    it('displays image size delta when positive', () => {
      const update = { ...defaultUpdate, image_size_delta: 5242880 } // 5 MB

      render(<UpdateCard update={update} />)
      expect(screen.getByText(/Size: \+5\.0 MB/)).toBeInTheDocument()
    })

    it('displays image size delta when negative', () => {
      const update = { ...defaultUpdate, image_size_delta: -2097152 } // -2 MB

      render(<UpdateCard update={update} />)
      expect(screen.getByText(/Size: -2\.0 MB/)).toBeInTheDocument()
    })
  })

  describe('Actions - Pending status', () => {
    it('renders approve and reject buttons', () => {
      const onApprove = vi.fn()
      const onReject = vi.fn()

      render(<UpdateCard update={defaultUpdate} onApprove={onApprove} onReject={onReject} />)

      expect(screen.getByText('Approve')).toBeInTheDocument()
      expect(screen.getByText('Reject')).toBeInTheDocument()
    })

    it('calls onApprove when approve button clicked', () => {
      const onApprove = vi.fn()

      render(<UpdateCard update={defaultUpdate} onApprove={onApprove} />)

      fireEvent.click(screen.getByText('Approve'))
      expect(onApprove).toHaveBeenCalledWith(defaultUpdate.id)
    })

    it('calls onReject when reject button clicked', () => {
      const onReject = vi.fn()

      render(<UpdateCard update={defaultUpdate} onReject={onReject} />)

      fireEvent.click(screen.getByText('Reject'))
      expect(onReject).toHaveBeenCalledWith(defaultUpdate.id)
    })
  })

  describe('Actions - Approved status', () => {
    const approvedUpdate = { ...defaultUpdate, status: 'approved' as const }

    it('renders apply button for approved updates', () => {
      const onApply = vi.fn()

      render(<UpdateCard update={approvedUpdate} onApply={onApply} />)

      expect(screen.getByText('Apply Update')).toBeInTheDocument()
    })

    it('calls onApply when apply button clicked', () => {
      const onApply = vi.fn()

      render(<UpdateCard update={approvedUpdate} onApply={onApply} />)

      fireEvent.click(screen.getByText('Apply Update'))
      expect(onApply).toHaveBeenCalledWith(approvedUpdate.id)
    })
  })

  describe('Actions - Pending Retry status', () => {
    const retryUpdate = {
      ...defaultUpdate,
      status: 'pending_retry' as const,
      last_error: 'Connection timeout',
      retry_count: 1,
    }

    it('renders retry-specific actions', () => {
      const onCancelRetry = vi.fn()
      const onReject = vi.fn()
      const onDelete = vi.fn()

      render(<UpdateCard update={retryUpdate} onCancelRetry={onCancelRetry} onReject={onReject} onDelete={onDelete} />)

      expect(screen.getByText('Cancel Retry')).toBeInTheDocument()
      expect(screen.getByText('Reject')).toBeInTheDocument()
    })

    it('displays error information', () => {
      render(<UpdateCard update={retryUpdate} />)

      expect(screen.getByText('Connection timeout')).toBeInTheDocument()
      expect(screen.getByText(/Retry 1\/3/)).toBeInTheDocument()
    })
  })

  describe('Loading state', () => {
    it('shows loading overlay when isApplying is true', () => {
      const { container } = render(<UpdateCard update={defaultUpdate} isApplying={true} />)

      // Check for loading spinner
      const spinner = container.querySelector('.animate-spin')
      expect(spinner).toBeInTheDocument()
    })

    it('disables buttons when isApplying is true', () => {
      const onApprove = vi.fn()

      render(<UpdateCard update={defaultUpdate} onApprove={onApprove} isApplying={true} />)

      const approveButton = screen.getByText('Approve')
      expect(approveButton).toBeDisabled()
    })

    it('applies blur effect to content when isApplying', () => {
      const { container } = render(<UpdateCard update={defaultUpdate} isApplying={true} />)

      const blurredElement = container.querySelector('.blur-sm')
      expect(blurredElement).toBeInTheDocument()
    })
  })

  describe('Reason icons', () => {
    it('shows shield icon for security updates', () => {
      const update = { ...defaultUpdate, reason_type: 'security' }

      const { container } = render(<UpdateCard update={update} />)
      expect(container.querySelector('.text-red-400')).toBeInTheDocument()
    })

    it('shows archive icon for stale updates', () => {
      const update = { ...defaultUpdate, reason_type: 'stale' }

      const { container } = render(<UpdateCard update={update} />)
      expect(container.querySelector('.text-orange-400')).toBeInTheDocument()
    })
  })
})
