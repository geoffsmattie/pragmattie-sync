import { afterEach, describe, expect, it, vi } from 'vitest'
import { getJson, orchErrorMessage, sendJson } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('repeats array params and skips empty ones', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetch)
    await getJson('/api/v1/leads', { status: ['new', 'working'], q: '', owner_id: null, limit: 25 })
    const url = new URL(fetch.mock.calls[0][0])
    expect(url.searchParams.getAll('status')).toEqual(['new', 'working'])
    expect(url.searchParams.has('q')).toBe(false)
    expect(url.searchParams.get('limit')).toBe('25')
  })

  it('surfaces the API error message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'Lead is already converted' }) }),
    )
    await expect(sendJson('POST', '/api/v1/leads/1/convert', {})).rejects.toThrow('Lead is already converted')
  })

  it('only suggests the orchestrator is down when it gave no answer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: [{ msg: 'Bad filter' }] }) }),
    )
    const answered = await getJson('/x').catch((err) => err)
    expect(orchErrorMessage(answered)).toBe('Bad filter')
    expect(orchErrorMessage(new TypeError('Failed to fetch'))).toBe(
      'Failed to fetch. Is the orchestrator service running on port 8001?',
    )
  })
})
