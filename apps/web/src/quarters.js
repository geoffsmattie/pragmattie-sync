// Calendar-quarter helpers (Q1 = Jan-Mar).
const pad = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

export function quarterOf(date = new Date()) {
  return { year: date.getFullYear(), q: Math.floor(date.getMonth() / 3) + 1 }
}

export function shiftQuarter({ year, q }, by) {
  const index = year * 4 + (q - 1) + by
  return { year: Math.floor(index / 4), q: (index % 4) + 1 }
}

export function quarterLabel({ year, q }) {
  return `${year}-Q${q}`
}

export function quarterRange({ year, q }) {
  const start = new Date(year, (q - 1) * 3, 1)
  const end = new Date(year, q * 3, 0)
  return { start: iso(start), end: iso(end) }
}
