/* eslint-disable react-refresh/only-export-components */
import { ReactElement, ReactNode } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Create a wrapper with all necessary providers
function AllTheProviders({ children }: { children: ReactNode }) {
  return (
    <BrowserRouter>
      {children}
    </BrowserRouter>
  )
}

// Custom render function that includes providers
function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, { wrapper: AllTheProviders, ...options })
}

// Fresh QueryClient per test, with retry disabled so failed requests don't
// hang the test runner waiting for retries.
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  client?: QueryClient
  // Set false when the test JSX already supplies its own Router (e.g. MemoryRouter).
  withRouter?: boolean
}

export function renderWithProviders(
  ui: ReactElement,
  { client, withRouter = true, ...options }: RenderWithProvidersOptions = {},
) {
  const queryClient = client ?? createTestQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    const inner = withRouter ? <BrowserRouter>{children}</BrowserRouter> : children
    return <QueryClientProvider client={queryClient}>{inner}</QueryClientProvider>
  }
  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) }
}

// Re-export everything from @testing-library/react
export * from '@testing-library/react'

// Override the default render with our custom render
export { customRender as render }
