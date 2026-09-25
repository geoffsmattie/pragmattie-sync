// Pure formatting helpers for the decision log, kept separate from the view so they're
// unit-testable without mounting a component (same split as src/board.js).

const FORECAST_KINDS = { sprint: 'Sprint', epic: 'Epic' }

export function subjectLabel(decision) {
  // A forecast's subject_id is its saved forecast row; its name is what a reader recognises.
  const forecastOf = FORECAST_KINDS[decision.subject_type]
  if (forecastOf) return `${forecastOf}: ${decision.output?.subject ?? `forecast #${decision.subject_id}`}`
  // A release is everything merged since the last deploy; its subject is the newest PR in it.
  if (decision.subject_type === 'release') {
    return decision.subject_id ? `Release up to PR #${decision.subject_id}` : 'Release'
  }
  const kind = decision.subject_type === 'issue' ? 'Issue' : 'PR'
  return `${kind} #${decision.subject_id}`
}

// rejected: a person's tier override that the rules turned down (see sdlc/agents/overrides.py)
// missed: CI failed a job the test selector would have skipped (see sdlc/suite_selector.py)
export const STATUS_COLORS = { ok: 'success', error: 'error', rejected: 'warning', missed: 'warning' }

export function statusColor(status) {
  return STATUS_COLORS[status] ?? 'default'
}
