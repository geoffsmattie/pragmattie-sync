import { describe, expect, it } from 'vitest'
import { money, moneyFull, monthLabel, percent, shortDate } from '../src/format'

describe('format', () => {
  it('formats money compactly and in full', () => {
    expect(money('1711000.00')).toBe('$1.7M')
    expect(money(60500)).toBe('$60.5K')
    expect(moneyFull('2330000.00')).toBe('$2,330,000')
  })

  it('formats percents and dates', () => {
    expect(percent(73.4)).toBe('73%')
    expect(shortDate('2026-09-18')).toBe('Sep 18, 2026')
    expect(shortDate('2026-09-18T14:00:00')).toBe('Sep 18, 2026')
    expect(monthLabel('2026-07')).toBe('Jul 2026')
  })
})
