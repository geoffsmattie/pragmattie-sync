const compact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
})
const full = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

/** $1.2M style, for tiles, cards and axes. */
export const money = (value) => compact.format(Number(value ?? 0))

/** $1,234,500 style, for tables and tooltips. */
export const moneyFull = (value) => full.format(Number(value ?? 0))

export const percent = (value) => `${Math.round(Number(value ?? 0))}%`

export function shortDate(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function monthLabel(yyyyMm) {
  const [y, m] = yyyyMm.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}
