import { afterEach, describe, expect, it, vi } from 'vitest'
import { getOrchJson, ORCH_URL } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

describe('orchestrator client', () => {
  it('calls the orchestrator service, not the CRM API', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetch)
    await getOrchJson('/api/v1/signals/cycle-time', { bucket: 'sprint' })
    const url = new URL(fetch.mock.calls[0][0])
    expect(url.origin).toBe(new URL(ORCH_URL).origin)
    expect(url.searchParams.get('bucket')).toBe('sprint')
  })
})
