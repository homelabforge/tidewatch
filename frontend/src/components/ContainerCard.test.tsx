import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ContainerCard from './ContainerCard'
import { mockContainer } from '../__tests__/mockData'
import { Container } from '../types'

describe('ContainerCard', () => {
  const defaultContainer: Container = {
    ...mockContainer,
    current_digest: null,
    compose_file: '/docker/compose.yml',
    service_name: 'nginx',
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
  }

  const defaultOnClick = vi.fn()

  describe('Basic rendering', () => {
    it('renders container name', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      const heading = container.querySelector('h3')
      expect(heading).toHaveTextContent('nginx')
    })

    it('renders image and tag', () => {
      render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      expect(screen.getByText('nginx:1.20')).toBeInTheDocument()
    })

    it('renders image name in info section', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      // Image name is extracted from full image path (nginx from nginx)
      // Check within the info grid section
      const infoGrid = container.querySelector('.grid')
      expect(infoGrid).toHaveTextContent('nginx')
    })

    it('renders updated date when available', () => {
      const container = {
        ...defaultContainer,
        updated_at: '2025-01-15T12:00:00Z'
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('Jan 15, 2025')).toBeInTheDocument()
    })

    it('renders N/A when updated_at is null', () => {
      const container = {
        ...defaultContainer,
        updated_at: ''
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('N/A')).toBeInTheDocument()
    })
  })

  describe('Update badge', () => {
    it('shows update badge with version when hasUpdate is true', () => {
      const container = {
        ...defaultContainer,
        latest_tag: '1.21.0'
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} hasUpdate={true} />)
      expect(screen.getByText(/Update Available/)).toBeInTheDocument()
      expect(screen.getByText(/1\.21\.0/)).toBeInTheDocument()
    })

    it('does not show update badge when hasUpdate is false', () => {
      render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} hasUpdate={false} />)
      expect(screen.queryByText(/Update Available/)).not.toBeInTheDocument()
    })

    it('does not show update badge by default', () => {
      render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      expect(screen.queryByText(/Update Available/)).not.toBeInTheDocument()
    })
  })

  describe('Policy display', () => {
    it('renders auto-update policy with correct icon and text', () => {
      const container = { ...defaultContainer, policy: 'auto' }
      const { container: elem } = render(<ContainerCard container={container} onClick={defaultOnClick} />)

      expect(screen.getByText('Auto (All)')).toBeInTheDocument()
      // AlertTriangle icon has text-orange-400 class
      const icon = elem.querySelector('.text-orange-400')
      expect(icon).toBeInTheDocument()
    })

    it('renders manual policy with correct icon and text', () => {
      const container = { ...defaultContainer, policy: 'manual' }
      const { container: elem } = render(<ContainerCard container={container} onClick={defaultOnClick} />)

      expect(screen.getByText('Manual')).toBeInTheDocument()
      // ToggleLeft icon has text-tide-text-muted class
      const icon = elem.querySelector('.text-tide-text-muted')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Scope display', () => {
    it('renders patch scope', () => {
      const container = { ...defaultContainer, scope: 'patch' }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText((content, element) => {
        return element?.tagName.toLowerCase() === 'span' && content === 'patch'
      })).toBeInTheDocument()
    })

    it('renders minor scope', () => {
      const container = { ...defaultContainer, scope: 'minor' }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText((content, element) => {
        return element?.tagName.toLowerCase() === 'span' && element?.className.includes('capitalize') && content === 'minor'
      })).toBeInTheDocument()
    })

    it('renders major scope', () => {
      const container = { ...defaultContainer, scope: 'major' }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText((content, element) => {
        return element?.tagName.toLowerCase() === 'span' && element?.className.includes('capitalize') && content === 'major'
      })).toBeInTheDocument()
    })
  })

  describe('Vulnerability display', () => {
    it('does not show vulnerability info when vulnforge is globally disabled', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 5,
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={false} />)
      expect(screen.queryByText(/vulnerabilities/)).not.toBeInTheDocument()
    })

    it('does not show vulnerability info when container vulnforge is disabled', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: false,
        current_vuln_count: 5,
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />)
      expect(screen.queryByText(/vulnerabilities/)).not.toBeInTheDocument()
    })

    it('shows green shield for zero vulnerabilities', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 0,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('No known vulnerabilities')).toBeInTheDocument()
      const greenText = elem.querySelector('.text-green-400')
      expect(greenText).toBeInTheDocument()
    })

    it('shows yellow alert for 1-5 vulnerabilities', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 3,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('3 vulnerabilities')).toBeInTheDocument()
      const yellowText = elem.querySelector('.text-yellow-400')
      expect(yellowText).toBeInTheDocument()
    })

    it('shows orange alert for 6-10 vulnerabilities', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 8,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('8 vulnerabilities')).toBeInTheDocument()
      const orangeText = elem.querySelector('.text-orange-400')
      expect(orangeText).toBeInTheDocument()
    })

    it('shows red alert for 11+ vulnerabilities', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 15,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('15 vulnerabilities')).toBeInTheDocument()
      const redText = elem.querySelector('.text-red-400')
      expect(redText).toBeInTheDocument()
    })
  })

  describe('Restart policy display', () => {
    it('does not show badge section when no restart features configured', () => {
      const container = {
        ...defaultContainer,
        restart_policy: '',
        auto_restart_enabled: false,
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.queryByText('Auto-Restart')).not.toBeInTheDocument()
    })

    it('shows Auto-Restart badge in Row 1 when enabled', () => {
      const container = {
        ...defaultContainer,
        restart_policy: '',
        auto_restart_enabled: true,
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('Auto-Restart')).toBeInTheDocument()
    })

    it('shows Auto-Restart badge when both Docker policy and auto-restart are configured', () => {
      const container = {
        ...defaultContainer,
        restart_policy: 'always',
        auto_restart_enabled: true,
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('Auto-Restart')).toBeInTheDocument()
    })
  })

  describe('Click handling', () => {
    it('calls onClick when card is clicked', () => {
      const onClick = vi.fn()
      const { container } = render(<ContainerCard container={defaultContainer} onClick={onClick} />)

      const card = container.firstChild as HTMLElement
      fireEvent.click(card)

      expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('applies cursor-pointer class for clickability indication', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      const card = container.firstChild as HTMLElement
      expect(card).toHaveClass('cursor-pointer')
    })
  })

  describe('Styling and layout', () => {
    it('applies base card styles', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      const card = container.firstChild as HTMLElement
      expect(card).toHaveClass(
        'bg-tide-surface',
        'border',
        'border-tide-border',
        'rounded-lg',
        'p-4'
      )
    })

    it('applies hover styles', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      const card = container.firstChild as HTMLElement
      expect(card).toHaveClass('hover:border-primary/50', 'transition-all')
    })

    it('applies group hover to title', () => {
      const { container } = render(<ContainerCard container={defaultContainer} onClick={defaultOnClick} />)
      const title = container.querySelector('h3')
      expect(title).toHaveClass('group-hover:text-primary', 'transition-colors')
    })
  })

  describe('Image path handling', () => {
    it('extracts short name from full image path', () => {
      const container = {
        ...defaultContainer,
        image: 'docker.io/library/nginx',
      }
      const { container: elem } = render(<ContainerCard container={container} onClick={defaultOnClick} />)
      // Should display just 'nginx' in the info section
      const infoGrid = elem.querySelector('.grid')
      expect(infoGrid).toHaveTextContent('nginx')
    })

    it('handles simple image names', () => {
      const container = {
        ...defaultContainer,
        image: 'postgres',
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('postgres')).toBeInTheDocument()
    })

    it('handles namespaced images', () => {
      const container = {
        ...defaultContainer,
        image: 'bitnami/postgresql',
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('postgresql')).toBeInTheDocument()
    })
  })

  describe('Edge cases', () => {
    it('handles null updated_at gracefully', () => {
      const container = {
        ...defaultContainer,
        updated_at: '',
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      expect(screen.getByText('N/A')).toBeInTheDocument()
    })

    it('handles empty scope with default', () => {
      const container = {
        ...defaultContainer,
        scope: '',
      }
      render(<ContainerCard container={container} onClick={defaultOnClick} />)
      // Component uses `scope || 'patch'` so should show 'patch'
      expect(screen.queryByText(/Scope:/)).toBeInTheDocument()
    })

    it('handles boundary vulnerability count (exactly 5)', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 5,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('5 vulnerabilities')).toBeInTheDocument()
      // At exactly 5, should still be yellow
      const yellowText = elem.querySelector('.text-yellow-400')
      expect(yellowText).toBeInTheDocument()
    })

    it('handles boundary vulnerability count (exactly 10)', () => {
      const container = {
        ...defaultContainer,
        vulnforge_enabled: true,
        current_vuln_count: 10,
      }
      const { container: elem } = render(
        <ContainerCard container={container} onClick={defaultOnClick} vulnforgeGlobalEnabled={true} />
      )

      expect(screen.getByText('10 vulnerabilities')).toBeInTheDocument()
      // At exactly 10, should still be orange
      const orangeText = elem.querySelector('.text-orange-400')
      expect(orangeText).toBeInTheDocument()
    })
  })
})
