// Pure helpers for the delivery forecast page, kept separate from the view so they're
// unit-testable without mounting a component (same split as src/board.js).

const DAY_MS = 86_400_000

/** "Mon Oct 05" from an ISO date, read as a calendar date (no timezone drift). */
export function dayLabel(iso) {
  if (!iso) return 'Not in sight'
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

/** How far a date moved: "+7 days", "−3 days", "No change", or null when unknown. */
export function shiftLabel(days) {
  if (days === null || days === undefined) return null
  if (days === 0) return 'No change'
  const n = Math.abs(days)
  return `${days > 0 ? '+' : '−'}${n} day${n === 1 ? '' : 's'}`
}

/** Later is bad news for a delivery date: later -> error, earlier -> success. */
export function shiftTone(days) {
  if (!days) return 'default'
  return days > 0 ? 'error' : 'success'
}

/** The chance of finishing a sprint on time, as a traffic light. */
export function onTimeTone(probability) {
  if (probability === null || probability === undefined) return 'default'
  if (probability >= 0.7) return 'success'
  if (probability >= 0.4) return 'warning'
  return 'error'
}

/** "3 open · 2 real" style honesty line for a forecast subject. */
export function mixLabel(forecast) {
  const open = `${forecast.remaining_items} open`
  if (forecast.kind === 'sprint') return `${open} · simulated sprint`
  if (!forecast.remaining_real) return `${open} · all simulated`
  return `${open} · ${forecast.remaining_real} real, ${forecast.remaining_items - forecast.remaining_real} simulated`
}

/** Issues closed per week from a per-working-day mean. */
export function perWeek(meanPerDay) {
  return Math.round(meanPerDay * 5 * 10) / 10
}

/**
 * Points for a small P50/P85 trail chart: x = forecast index, y = days after the earliest date
 * shown. Forecasts with no date ("not in sight") are skipped. Returns null with fewer than two.
 */
export function trailPoints(trail) {
  const rows = (trail ?? []).filter((t) => t.p50 && t.p85)
  if (rows.length < 2) return null
  const toDay = (iso) => {
    const [y, m, d] = iso.split('-').map(Number)
    return Date.UTC(y, m - 1, d) / DAY_MS
  }
  const lo = Math.min(...rows.map((t) => toDay(t.p50)))
  const hi = Math.max(...rows.map((t) => toDay(t.p85)))
  return {
    span: Math.max(1, hi - lo),
    p50: rows.map((t, i) => [i, toDay(t.p50) - lo]),
    p85: rows.map((t, i) => [i, toDay(t.p85) - lo]),
    count: rows.length,
  }
}

/** Subjects whose latest saved forecast changed between two polls (for a highlight flash). */
export function changedSubjects(before, after) {
  const was = new Map(
    [before?.sprint, ...(before?.epics ?? [])].filter(Boolean).map((f) => [f.subject, f.id]),
  )
  const changed = new Set()
  for (const f of [after?.sprint, ...(after?.epics ?? [])].filter(Boolean)) {
    if (was.has(f.subject) && was.get(f.subject) !== f.id) changed.add(f.subject)
  }
  return changed
}

export const ACTION_LABELS = { defer: 'Defer', reassign: 'Reassign', split: 'Split' }

/**
 * The measured effect of a planner option, e.g. "On-time 22% → 71% · P85 Tue, Sep 29 → Fri, Sep 25".
 * Code measures this by re-running the forecast; the model never supplies it. Null when the
 * option isn't something the simulation can measure (reassigning or splitting).
 */
export function effectLabel(effect) {
  if (!effect) return null
  const pct = (p) => `${Math.round(p * 100)}%`
  const parts = [`On-time ${pct(effect.from.on_time_probability)} → ${pct(effect.on_time_probability)}`]
  if (effect.from.p85 !== effect.p85) {
    parts.push(`P85 ${dayLabel(effect.from.p85)} → ${dayLabel(effect.p85)}`)
  }
  return parts.join(' · ')
}
