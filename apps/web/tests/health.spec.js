import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useHealthStore } from '../src/stores/health'

describe('health store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('reports healthy when the API and database are ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', database: 'ok' }),
    }))
    const store = useHealthStore()
    await store.check()
    expect(store.isHealthy).toBe(true)
  })

  it('reports down when the API cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))
    const store = useHealthStore()
    await store.check()
    expect(store.status).toBe('down')
    expect(store.isHealthy).toBe(false)
    expect(store.error).toBe('Failed to fetch')
  })
})
