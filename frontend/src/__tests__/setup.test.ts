import { describe, it, expect } from 'vitest'

describe('Test Infrastructure', () => {
  it('should have testing environment set up', () => {
    expect(true).toBe(true)
  })

  it('should have global fetch mocked', () => {
    expect(globalThis.fetch).toBeDefined()
  })

  it('should have EventSource mocked', () => {
    expect(globalThis.EventSource).toBeDefined()
  })

  it('should have window.matchMedia mocked', () => {
    expect(window.matchMedia).toBeDefined()
  })
})
