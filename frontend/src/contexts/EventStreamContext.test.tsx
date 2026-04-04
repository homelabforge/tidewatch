import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'
import { EventStreamProvider } from './EventStreamContext'
import { AuthContext, type AuthContextType } from './AuthContext'

// Mock EventSource
class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener = vi.fn()
}

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

function renderWithAuth(authContext: AuthContextType) {
  return render(
    <AuthContext.Provider value={authContext}>
      <EventStreamProvider>
        <div>test child</div>
      </EventStreamProvider>
    </AuthContext.Provider>
  )
}

describe('EventStreamContext', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not connect when isLoading is true', () => {
    const authContext = createMockAuthContext({ isLoading: true, isAuthenticated: false })
    renderWithAuth(authContext)

    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('does not connect when isAuthenticated is false', () => {
    const authContext = createMockAuthContext({ isLoading: false, isAuthenticated: false })
    renderWithAuth(authContext)

    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('connects when isAuthenticated is true', () => {
    const authContext = createMockAuthContext({ isLoading: false, isAuthenticated: true })
    renderWithAuth(authContext)

    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toContain('/api/v1/events/stream')
  })

  it('disconnects on logout', () => {
    const authContext = createMockAuthContext({ isLoading: false, isAuthenticated: true })
    const { rerender } = renderWithAuth(authContext)

    expect(MockEventSource.instances).toHaveLength(1)
    const firstInstance = MockEventSource.instances[0]

    // Simulate logout by re-rendering with isAuthenticated: false
    const loggedOutContext = createMockAuthContext({ isLoading: false, isAuthenticated: false })
    act(() => {
      rerender(
        <AuthContext.Provider value={loggedOutContext}>
          <EventStreamProvider>
            <div>test child</div>
          </EventStreamProvider>
        </AuthContext.Provider>
      )
    })

    expect(firstInstance.close).toHaveBeenCalled()
  })
})
