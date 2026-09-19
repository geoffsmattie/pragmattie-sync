import { describe, expect, it } from 'vitest'
import { quarterLabel, quarterOf, quarterRange, shiftQuarter } from '../src/quarters'

describe('quarters', () => {
  it('finds the quarter for a date', () => {
    expect(quarterOf(new Date(2026, 8, 18))).toEqual({ year: 2026, q: 3 })
    expect(quarterOf(new Date(2026, 0, 1))).toEqual({ year: 2026, q: 1 })
  })

  it('shifts across year boundaries', () => {
    expect(quarterLabel(shiftQuarter({ year: 2026, q: 4 }, 1))).toBe('2027-Q1')
    expect(quarterLabel(shiftQuarter({ year: 2026, q: 1 }, -2))).toBe('2025-Q3')
  })

  it('returns inclusive date ranges', () => {
    expect(quarterRange({ year: 2026, q: 3 })).toEqual({ start: '2026-07-01', end: '2026-09-30' })
    expect(quarterRange({ year: 2026, q: 1 })).toEqual({ start: '2026-01-01', end: '2026-03-31' })
  })
})
