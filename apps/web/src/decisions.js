// Pure formatting helpers for the decision log, kept separate from the view so they're
// unit-testable without mounting a component (same split as src/board.js).

export function subjectLabel(decision) {
  const kind = decision.subject_type === 'issue' ? 'Issue' : 'PR'
  return `${kind} #${decision.subject_id}`
}

export const STATUS_COLORS = { ok: 'success', error: 'error' }

export function statusColor(status) {
  return STATUS_COLORS[status] ?? 'default'
}
