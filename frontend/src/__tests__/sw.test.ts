/**
 * Service worker fetch-handler regression tests.
 *
 * Guards the OIDC-login-shows-offline bug: the SW must NOT intercept
 * navigations to backend (/api/) endpoints. The OIDC callback navigates the
 * top-level document to /api/v1/auth/oidc/callback and the server-side token
 * exchange can take >5s; if the SW races it against its 5s navigation timeout
 * it serves offline.html over a login that actually succeeded, and the user's
 * Retry re-hits the one-time OIDC state ("Invalid or expired state").
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
// Load the service worker source as a raw string (Vite ?raw import) so we can
// run its fetch handler against synthetic events without a real SW runtime.
import swSource from '../../public/sw.js?raw'

const ORIGIN = 'https://tidewatch.test'

type FetchHandler = (event: unknown) => void

function loadSwFetchHandler(): FetchHandler {
  const listeners: Record<string, FetchHandler> = {}
  const fakeSelf = {
    location: { href: `${ORIGIN}/sw.js?v=test`, origin: ORIGIN },
    addEventListener: (type: string, fn: FetchHandler) => {
      listeners[type] = fn
    },
    skipWaiting: () => {},
    clients: { claim: () => {} },
  }
  // sw.js references bare `self`; inject our controlled stand-in. Other globals
  // (fetch, caches, URL, setTimeout) come from the test environment.
   
  new Function('self', swSource)(fakeSelf)
  return listeners.fetch
}

function makeEvent(opts: {
  path: string
  mode?: string
  destination?: string
  method?: string
}) {
  const respondWith = vi.fn()
  const event = {
    request: {
      url: `${ORIGIN}${opts.path}`,
      mode: opts.mode ?? 'navigate',
      destination: opts.destination ?? 'document',
      method: opts.method ?? 'GET',
    },
    respondWith,
    waitUntil: vi.fn(),
  }
  return { event, respondWith }
}

describe('service worker fetch handler', () => {
  let handler: FetchHandler

  beforeEach(() => {
    vi.useFakeTimers()
    // Keep every branch from touching the real network or cache. fetch resolves
    // to a real Response (so .clone()/.ok work) and caches is a complete no-op
    // stub, so no handler path rejects unhandled.
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 200 }))))
    const cache = {
      match: vi.fn(() => Promise.resolve(undefined)),
      put: vi.fn(() => Promise.resolve()),
    }
    vi.stubGlobal('caches', {
      open: vi.fn(() => Promise.resolve(cache)),
      match: vi.fn(() => Promise.resolve(undefined)),
    })
    handler = loadSwFetchHandler()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('does NOT intercept navigations to /api/ backend endpoints (OIDC callback)', () => {
    const { event, respondWith } = makeEvent({
      path: '/api/v1/auth/oidc/callback?code=abc&state=xyz',
    })
    handler(event)
    // Bypassed → browser handles it natively, no offline-fallback race.
    expect(respondWith).not.toHaveBeenCalled()
  })

  it('does NOT intercept document-destination prefetch of /api/ endpoints', () => {
    const { event, respondWith } = makeEvent({
      path: '/api/v1/auth/oidc/login',
      mode: 'no-cors',
      destination: 'document',
    })
    handler(event)
    expect(respondWith).not.toHaveBeenCalled()
  })

  it('still handles SPA shell navigations (non-/api routes)', () => {
    const { event, respondWith } = makeEvent({ path: '/settings' })
    handler(event)
    // SPA routes keep the network-first + offline.html fallback behaviour.
    expect(respondWith).toHaveBeenCalledTimes(1)
  })

  it('still handles non-navigation /api/ fetches via the API branch', () => {
    const { event, respondWith } = makeEvent({
      path: '/api/v1/containers',
      mode: 'cors',
      destination: '',
    })
    handler(event)
    expect(respondWith).toHaveBeenCalledTimes(1)
  })
})
