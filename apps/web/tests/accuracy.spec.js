import { describe, expect, it } from 'vitest'
import { headlines, pct, realState, shortSprint } from '../src/accuracy'

const report = {
  forecast: { p85_hit_rate: 0.833, graded: 12, targets: { p85_hit_rate: 0.85, p50_hit_rate: 0.5 } },
  risk: { recall: 0.8, caught: 12, incident_prs: 15, t0_incidents: 1 },
  triage: { kept_rate: 1, corrected: 0, total: 40 },
  test_selector: { missed: 0, total: 0 },
}

describe('accuracy helpers', () => {
  it('formats rates and sprint names', () => {
    expect(pct(0.833)).toBe('83%')
    expect(pct(null)).toBe('—')
    expect(shortSprint('Sprint 12')).toBe('S12')
  })

  it('says when a real trend has enough points to draw', () => {
    expect(realState({ total: 0 }, 5)).toBe('empty')
    expect(realState({ total: 3 }, 5)).toBe('thin')
    expect(realState({ total: 5 }, 5)).toBe('enough')
  })

  it('builds the four headlines, marking the simulated ones', () => {
    const tiles = headlines(report)
    expect(tiles.map((t) => [t.key, t.value, t.simulated])).toEqual([
      ['forecast', '83%', true],
      ['risk', '80%', true],
      ['triage', '100%', false],
      ['selector', '—', false],
    ])
    expect(tiles[1].target).toBe('12 of 15')
  })
})
