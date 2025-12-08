import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatusBadge from './StatusBadge'

describe('StatusBadge', () => {
  describe('Restart-specific statuses', () => {
    it('renders restarted status with blue styling', () => {
      render(<StatusBadge status="restarted" />)
      const badge = screen.getByText('Restarted')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-blue-500/20', 'text-blue-400', 'border-blue-500/30')
    })

    it('renders failed_to_restart status with red styling', () => {
      render(<StatusBadge status="failed_to_restart" />)
      const badge = screen.getByText('Failed To Restart')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-red-500/20', 'text-red-400', 'border-red-500/30')
    })

    it('renders crashed status with orange styling', () => {
      render(<StatusBadge status="crashed" />)
      const badge = screen.getByText('Crashed')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-orange-500/20', 'text-orange-400', 'border-orange-500/30')
    })
  })

  describe('Update statuses', () => {
    it('renders completed status with green styling', () => {
      render(<StatusBadge status="completed" />)
      const badge = screen.getByText('Completed')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-green-500/20', 'text-green-400', 'border-green-500/30')
    })

    it('renders success status with green styling', () => {
      render(<StatusBadge status="success" />)
      const badge = screen.getByText('Success')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-green-500/20', 'text-green-400', 'border-green-500/30')
    })

    it('renders running status with green styling', () => {
      render(<StatusBadge status="running" />)
      const badge = screen.getByText('Running')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-green-500/20', 'text-green-400', 'border-green-500/30')
    })

    it('renders pending status with yellow styling', () => {
      render(<StatusBadge status="pending" />)
      const badge = screen.getByText('Pending')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-yellow-500/20', 'text-yellow-400', 'border-yellow-500/30')
    })

    it('renders pending_retry status with orange styling', () => {
      render(<StatusBadge status="pending_retry" />)
      const badge = screen.getByText('Pending Retry')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-orange-500/20', 'text-orange-400', 'border-orange-500/30')
    })

    it('renders approved status with blue styling', () => {
      render(<StatusBadge status="approved" />)
      const badge = screen.getByText('Approved')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-blue-500/20', 'text-blue-400', 'border-blue-500/30')
    })

    it('renders applied status with primary styling', () => {
      render(<StatusBadge status="applied" />)
      const badge = screen.getByText('Applied')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-primary/20', 'text-primary', 'border-primary/30')
    })

    it('renders rejected status with gray styling', () => {
      render(<StatusBadge status="rejected" />)
      const badge = screen.getByText('Rejected')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-tide-border-light/20', 'text-tide-text-muted', 'border-gray-500/30')
    })

    it('renders failed status with red styling', () => {
      render(<StatusBadge status="failed" />)
      const badge = screen.getByText('Failed')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-red-500/20', 'text-red-400', 'border-red-500/30')
    })

    it('renders error status with red styling', () => {
      render(<StatusBadge status="error" />)
      const badge = screen.getByText('Error')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-red-500/20', 'text-red-400', 'border-red-500/30')
    })

    it('renders stopped status with gray styling', () => {
      render(<StatusBadge status="stopped" />)
      const badge = screen.getByText('Stopped')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-tide-border-light/20', 'text-tide-text-muted', 'border-gray-500/30')
    })

    it('renders exited status with gray styling', () => {
      render(<StatusBadge status="exited" />)
      const badge = screen.getByText('Exited')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-tide-border-light/20', 'text-tide-text-muted', 'border-gray-500/30')
    })

    it('renders rolled_back status with yellow styling', () => {
      render(<StatusBadge status="rolled_back" />)
      const badge = screen.getByText('Rolled Back')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-yellow-500/20', 'text-yellow-400', 'border-yellow-500/30')
    })
  })

  describe('Status label formatting', () => {
    it('converts snake_case to Title Case', () => {
      render(<StatusBadge status="pending_retry" />)
      expect(screen.getByText('Pending Retry')).toBeInTheDocument()
    })

    it('capitalizes first letter of single words', () => {
      render(<StatusBadge status="pending" />)
      expect(screen.getByText('Pending')).toBeInTheDocument()
    })

    it('handles multi-word statuses', () => {
      render(<StatusBadge status="failed_to_restart" />)
      expect(screen.getByText('Failed To Restart')).toBeInTheDocument()
    })
  })

  describe('Case insensitivity', () => {
    it('handles UPPERCASE status', () => {
      render(<StatusBadge status="SUCCESS" />)
      const badge = screen.getByText('Success')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-green-500/20', 'text-green-400', 'border-green-500/30')
    })

    it('handles MixedCase status', () => {
      render(<StatusBadge status="Pending" />)
      const badge = screen.getByText('Pending')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-yellow-500/20', 'text-yellow-400', 'border-yellow-500/30')
    })
  })

  describe('Unknown/default status', () => {
    it('renders unknown status with default gray styling', () => {
      render(<StatusBadge status="unknown_status" />)
      const badge = screen.getByText('Unknown Status')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveClass('bg-tide-border-light/20', 'text-tide-text-muted', 'border-gray-500/30')
    })
  })

  describe('Custom className prop', () => {
    it('applies custom className alongside default classes', () => {
      render(<StatusBadge status="success" className="custom-class" />)
      const badge = screen.getByText('Success')
      expect(badge).toHaveClass('custom-class')
      expect(badge).toHaveClass('bg-green-500/20') // Still has default classes
    })

    it('works without custom className', () => {
      render(<StatusBadge status="pending" />)
      const badge = screen.getByText('Pending')
      expect(badge).toHaveClass('px-2.5', 'py-0.5', 'rounded-full')
    })
  })

  describe('Default styling', () => {
    it('applies badge base classes', () => {
      render(<StatusBadge status="success" />)
      const badge = screen.getByText('Success')
      expect(badge).toHaveClass(
        'px-2.5',
        'py-0.5',
        'rounded-full',
        'text-xs',
        'font-medium',
        'border'
      )
    })
  })
})
