import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

// Cleanup after each test
afterEach(() => {
  cleanup()
})

// Mock fetch (Tidewatch uses native fetch, not axios)
globalThis.fetch = vi.fn()

// Mock window.matchMedia (for responsive components)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // Deprecated but some libs still use
    removeListener: vi.fn(), // Deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver (for lazy loading/visibility detection)
globalThis.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
} as unknown as {
  new (): IntersectionObserver
}

// Mock ResizeObserver (for responsive components)
globalThis.ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
} as unknown as {
  new (): ResizeObserver
}

// Mock EventSource (CRITICAL for Tidewatch SSE testing)
globalThis.EventSource = class EventSource {
  static instances: EventSource[] = []

  url: string
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  CONNECTING = 0
  OPEN = 1
  CLOSED = 2

  constructor(url: string) {
    this.url = url
    EventSource.instances.push(this)
    // Simulate connection opening
    setTimeout(() => {
      this.readyState = this.OPEN
      if (this.onopen) {
        this.onopen(new Event('open'))
      }
    }, 0)
  }

  addEventListener(
    type: string,
    listener: (event: Event | MessageEvent) => void
  ) {
    if (type === 'open' && !this.onopen) {
      this.onopen = listener
    } else if (type === 'message' && !this.onmessage) {
      this.onmessage = listener
    } else if (type === 'error' && !this.onerror) {
      this.onerror = listener
    }
  }

  removeEventListener() {
    // Mock implementation
  }

  close() {
    this.readyState = this.CLOSED
    EventSource.instances = EventSource.instances.filter(
      instance => instance !== this
    )
  }

  // Helper method for tests to simulate receiving events
  static simulateEvent(data: unknown) {
    this.instances.forEach(instance => {
      if (instance.onmessage && instance.readyState === instance.OPEN) {
        instance.onmessage(
          new MessageEvent('message', {
            data: JSON.stringify(data),
          })
        )
      }
    })
  }

  // Helper method for tests to simulate errors
  static simulateError() {
    this.instances.forEach(instance => {
      if (instance.onerror) {
        instance.onerror(new Event('error'))
      }
    })
  }

  // Helper method to clear all instances (for test cleanup)
  static clearAll() {
    this.instances.forEach(instance => instance.close())
    this.instances = []
  }
} as unknown as {
  new (url: string): EventSource
  simulateEvent: (data: unknown) => void
  simulateError: () => void
  clearAll: () => void
}

// Clear EventSource instances after each test
afterEach(() => {
  (globalThis.EventSource as unknown as { clearAll: () => void }).clearAll()
  vi.clearAllMocks()
})
