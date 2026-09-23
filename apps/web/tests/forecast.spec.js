import { describe, expect, it } from 'vitest'
import {
  changedSubjects,
  dayLabel,
  mixLabel,
  onTimeTone,
  perWeek,
  shiftLabel,
  shiftTone,
  trailPoints,
} from '../src/forecast'

describe('dayLabel', () => {
  it('reads an ISO date as a calendar day and says when there is none', () => {
    expect(dayLabel('2026-10-05')).toContain('5')
    expect(dayLabel(null)).toBe('Not in sight')
  })
})

describe('shiftLabel and shiftTone', () => {
  it('describes a move and colours later as bad news', () => {
    expect(shiftLabel(7)).toBe('+7 days')
    expect(shiftLabel(-1)).toBe('−1 day')
    expect(shiftLabel(0)).toBe('No change')
    expect(shiftLabel(null)).toBeNull()
    expect(shiftTone(7)).toBe('error')
    expect(shiftTone(-2)).toBe('success')
    expect(shiftTone(0)).toBe('default')
  })
})

describe('onTimeTone', () => {
  it('is a traffic light on the on-time chance', () => {
    expect(onTimeTone(0.8)).toBe('success')
    expect(onTimeTone(0.5)).toBe('warning')
    expect(onTimeTone(0.1)).toBe('error')
    expect(onTimeTone(null)).toBe('default')
  })
})

describe('mixLabel', () => {
  it('always says how much is simulated', () => {
    expect(mixLabel({ kind: 'sprint', remaining_items: 5 })).toBe('5 open · simulated sprint')
    expect(mixLabel({ kind: 'epic', remaining_items: 6, remaining_real: 0 })).toBe(
      '6 open · all simulated',
    )
    expect(mixLabel({ kind: 'epic', remaining_items: 10, remaining_real: 2 })).toBe(
      '10 open · 2 real, 8 simulated',
    )
  })
})

describe('perWeek', () => {
  it('turns a per-working-day mean into a weekly rate', () => {
    expect(perWeek(0.22)).toBe(1.1)
  })
})

describe('trailPoints', () => {
  it('needs two dated forecasts and scales days from the earliest', () => {
    expect(trailPoints([{ p50: '2026-11-01', p85: '2026-11-10' }])).toBeNull()
    const t = trailPoints([
      { p50: '2026-11-01', p85: '2026-11-10' },
      { p50: null, p85: null },
      { p50: '2026-11-08', p85: '2026-11-20' },
    ])
    expect(t.count).toBe(2)
    expect(t.span).toBe(19)
    expect(t.p50).toEqual([
      [0, 0],
      [1, 7],
    ])
    expect(t.p85[1]).toEqual([1, 19])
  })
})

describe('changedSubjects', () => {
  it('flags subjects whose latest forecast is a new one', () => {
    const before = { sprint: { subject: 'Sprint 13', id: 1 }, epics: [{ subject: 'A', id: 2 }] }
    const after = {
      sprint: { subject: 'Sprint 13', id: 1 },
      epics: [
        { subject: 'A', id: 7 },
        { subject: 'B', id: 8 },
      ],
    }
    expect([...changedSubjects(before, after)]).toEqual(['A'])
    expect(changedSubjects(null, after).size).toBe(0)
  })
})
