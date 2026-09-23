// Pure formatting helpers for the decision log, kept separate from the view so they're
// unit-testable without mounting a component (same split as src/board.js).

const FORECAST_KINDS = { sprint: 'Sprint', epic: 'Epic' }

export function subjectLabel(decision) {
  // A forecast's subject_id is its saved forecast row; its name is what a reader recognises.
  const forecastOf = FORECAST_KINDS[decision.subject_type]
  if (forecastOf) return `${forecastOf}: ${decision.output?.subject ?? `forecast #${decision.subject_id}`}`
  const kind = decision.subject_type === 'issue' ? 'Issue' : 'PR'
  return `${kind} #${decision.subject_id}`
}

export const STATUS_COLORS = { ok: 'success', error: 'error' }

export function statusColor(status) {
  return STATUS_COLORS[status] ?? 'default'
}
