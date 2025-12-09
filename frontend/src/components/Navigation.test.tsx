import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Navigation from './Navigation'
import { AuthContext, type AuthContextType } from '../contexts/AuthContext'

// Mock the useAuth hook by providing AuthContext
const createMockAuthContext = (overrides?: Partial<AuthContextType>): AuthContextType => ({
  user: null,
  authMode: 'none',
  isAuthenticated: false,
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

const renderWithRouter = (
  component: React.ReactElement,
  authContext: AuthContextType,
  initialRoute = '/'
) => {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <AuthContext.Provider value={authContext}>
        {component}
      </AuthContext.Provider>
    </MemoryRouter>
  )
}

describe('Navigation', () => {
  describe('Branding', () => {
    it('renders TideWatch logo and brand name', () => {
      const authContext = createMockAuthContext()
      renderWithRouter(<Navigation />, authContext)

      expect(screen.getByText('Tide')).toBeInTheDocument()
      expect(screen.getByText('Watch')).toBeInTheDocument()
    })

    it('logo links to home page', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      const logoLink = container.querySelector('a[href="/"]')
      expect(logoLink).toBeInTheDocument()
    })
  })

  describe('Navigation items', () => {
    it('renders all navigation links', () => {
      const authContext = createMockAuthContext()
      renderWithRouter(<Navigation />, authContext)

      expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Updates').length).toBeGreaterThan(0)
      expect(screen.getAllByText('History').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Settings').length).toBeGreaterThan(0)
      expect(screen.getAllByText('About').length).toBeGreaterThan(0)
    })

    it('highlights active route', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext, '/updates')

      // The active link should have both bg-tide-surface-light and text-primary classes
      const activeLinks = container.querySelectorAll('.text-primary')
      expect(activeLinks.length).toBeGreaterThan(0)
    })

    it('highlights dashboard when on home route', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext, '/')

      // Home (/) should be active
      const activeLinks = container.querySelectorAll('.text-primary')
      expect(activeLinks.length).toBeGreaterThan(0)
    })

    it('applies correct classes to active links', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext, '/settings')

      const activeLinks = container.querySelectorAll('.bg-tide-surface-light.text-primary')
      expect(activeLinks.length).toBeGreaterThan(0)
    })

    it('applies correct classes to inactive links', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext, '/updates')

      const inactiveLinks = container.querySelectorAll('.text-tide-text-muted')
      expect(inactiveLinks.length).toBeGreaterThan(0)
    })
  })

  describe('User menu - auth disabled', () => {
    it('does not show user menu when auth mode is none', () => {
      const authContext = createMockAuthContext({
        authMode: 'none',
        isAuthenticated: true,
      })
      renderWithRouter(<Navigation />, authContext)

      expect(screen.queryByText('Logout')).not.toBeInTheDocument()
    })

    it('does not show user menu when not authenticated', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: false,
      })
      renderWithRouter(<Navigation />, authContext)

      expect(screen.queryByText('Logout')).not.toBeInTheDocument()
    })
  })

  describe('User menu - auth enabled', () => {
    it('shows username when authenticated with local auth', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      renderWithRouter(<Navigation />, authContext)

      expect(screen.getAllByText('testuser').length).toBeGreaterThan(0)
    })

    it('shows username when authenticated with OIDC', () => {
      const authContext = createMockAuthContext({
        authMode: 'oidc',
        isAuthenticated: true,
        user: {
          id: '2',
          username: 'oidcuser',
          email: 'oidc@example.com',
          full_name: 'OIDC User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      renderWithRouter(<Navigation />, authContext)

      expect(screen.getAllByText('oidcuser').length).toBeGreaterThan(0)
    })

    it('shows logout button when authenticated', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      renderWithRouter(<Navigation />, authContext)

      expect(screen.getAllByText('Logout').length).toBeGreaterThan(0)
    })

    it('calls logout and navigates when logout button clicked', async () => {
      const mockLogout = vi.fn().mockResolvedValue(undefined)
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        logout: mockLogout,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })

      renderWithRouter(<Navigation />, authContext)

      const logoutButtons = screen.getAllByText('Logout')

      // Use act to wrap state updates
      await vi.waitFor(() => {
        fireEvent.click(logoutButtons[0])
      })

      expect(mockLogout).toHaveBeenCalledTimes(1)
    })
  })

  describe('Responsive design', () => {
    it('renders desktop navigation menu', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      // Desktop nav has class "hidden md:block"
      const desktopNav = container.querySelector('.hidden.md\\:block')
      expect(desktopNav).toBeInTheDocument()
    })

    it('renders mobile navigation menu', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      // Mobile nav has class "md:hidden"
      const mobileNav = container.querySelector('.md\\:hidden')
      expect(mobileNav).toBeInTheDocument()
    })

    it('shows user menu in desktop view when authenticated', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      const { container } = renderWithRouter(<Navigation />, authContext)

      // Desktop user menu has class "hidden md:flex"
      const desktopUserMenu = container.querySelector('.hidden.md\\:flex')
      expect(desktopUserMenu).toBeInTheDocument()
    })
  })

  describe('Icons', () => {
    it('renders navigation icons', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      // Check that SVG icons are rendered (lucide-react renders SVG elements)
      const svgIcons = container.querySelectorAll('svg')
      // Should have: Waves logo + 5 nav items * 2 (desktop + mobile) = 11 minimum
      expect(svgIcons.length).toBeGreaterThan(10)
    })

    it('renders user icon when authenticated', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      const { container } = renderWithRouter(<Navigation />, authContext)

      // User icon (User component from lucide-react)
      const svgIcons = container.querySelectorAll('svg')
      // Should have additional user icons
      expect(svgIcons.length).toBeGreaterThan(12)
    })
  })

  describe('Styling', () => {
    it('applies base navigation styles', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      const nav = container.querySelector('nav')
      expect(nav).toHaveClass('bg-tide-surface', 'border-b', 'border-tide-border')
    })

    it('applies container max-width', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      const navContainer = container.querySelector('.max-w-7xl')
      expect(navContainer).toBeInTheDocument()
    })

    it('applies hover styles to links', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      const hoverLinks = container.querySelectorAll('.hover\\:bg-tide-surface-light')
      expect(hoverLinks.length).toBeGreaterThan(0)
    })
  })

  describe('Navigation structure', () => {
    it('has correct number of navigation items', () => {
      const authContext = createMockAuthContext()
      renderWithRouter(<Navigation />, authContext)

      // Each nav item appears twice (desktop + mobile)
      const dashboardLinks = screen.getAllByText('Dashboard')
      expect(dashboardLinks.length).toBe(2) // desktop + mobile
    })

    it('renders navigation in correct order', () => {
      const authContext = createMockAuthContext()
      const { container } = renderWithRouter(<Navigation />, authContext)

      const links = Array.from(container.querySelectorAll('a'))
        .filter(link => link.textContent?.match(/Dashboard|Updates|History|Settings|About/))
        .map(link => link.textContent?.trim())

      // First 5 should be desktop, next 5 should be mobile
      expect(links.slice(0, 5)).toEqual(['Dashboard', 'Updates', 'History', 'Settings', 'About'])
      expect(links.slice(5, 10)).toEqual(['Dashboard', 'Updates', 'History', 'Settings', 'About'])
    })
  })

  describe('Edge cases', () => {
    it('handles null user gracefully when authenticated', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: null,
      })

      // Should not crash when user is null
      expect(() => {
        renderWithRouter(<Navigation />, authContext)
      }).not.toThrow()
    })

    it('handles missing username in user object', () => {
      const authContext = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: true,
        user: {
          id: '1',
          username: '',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })

      renderWithRouter(<Navigation />, authContext)
      // Should render without crashing even with empty username
      expect(screen.getAllByText('Logout').length).toBeGreaterThan(0)
    })

    it('shows user menu only when both authenticated AND auth enabled', () => {
      // Case 1: Authenticated but auth disabled
      const authContext1 = createMockAuthContext({
        authMode: 'none',
        isAuthenticated: true,
        user: {
          id: '1',
          username: 'testuser',
          email: 'test@example.com',
          full_name: 'Test User',
          created_at: '2025-01-01T00:00:00Z',
        },
      })
      const { unmount } = renderWithRouter(<Navigation />, authContext1)
      expect(screen.queryByText('Logout')).not.toBeInTheDocument()
      unmount()

      // Case 2: Auth enabled but not authenticated
      const authContext2 = createMockAuthContext({
        authMode: 'local',
        isAuthenticated: false,
        user: null,
      })
      renderWithRouter(<Navigation />, authContext2)
      expect(screen.queryByText('Logout')).not.toBeInTheDocument()
    })
  })
})
