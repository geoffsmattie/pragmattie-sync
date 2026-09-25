// Pure logic behind the delivery board view: client-side replay and column stats, so
// BoardView.vue stays a thin rendering layer and this stays unit-testable without mounting.

/** A card's column as of `asOf`, from its `transitions` list (assumed chronological — see
 * orchestrator/sdlc/board.py's Card.transitions docstring: "for replay"). Returns null if the
 * card hasn't entered the pipeline yet at that point in time. */
export function cardAtTime(card, asOf) {
  const t = asOf.getTime()
  let column = null
  let enteredAt = null
  for (const [name, at] of card.transitions) {
    if (new Date(at).getTime() <= t) {
      column = name
      enteredAt = at
    } else break
  }
  if (column === null) return null
  return { ...card, column, entered_column_at: enteredAt }
}

/** The release gate's verdict on a merged card's release, as a chip: null when there is none.
 * A hold clears by itself (an incident closes, CI finishes, a sign-off arrives); a block needs a
 * new commit. See orchestrator/sdlc/agents/release_gate.py. */
export function releaseChip(card) {
  const r = card.release
  if (!r || card.column !== 'merged') return null
  const title = r.description || r.reasons.join('; ')
  if (r.verdict === 'hold') return { text: 'Release held', color: 'warning', title }
  if (r.verdict === 'blocked') return { text: 'Release blocked', color: 'error', title }
  if (r.verdict === 'release') return { text: 'Releasing', color: 'success', title }
  return null
}

export function median(nums) {
  if (!nums.length) return null
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** {title, wip, median_age_hours} per column, matching orchestrator/sdlc/board.py's
 * serialized `columns` shape, computed client-side for replay frames (which never touch
 * the network — the server's own stats only cover the live, unreplayed board). */
export function columnStatsAt(cards, now, columns) {
  const out = {}
  for (const { key, title } of columns) {
    const items = cards.filter((c) => c.column === key)
    const ages = items.map((c) => (now - new Date(c.entered_column_at)) / 3_600_000)
    out[key] = {
      title,
      wip: items.length,
      median_age_hours: ages.length ? Math.round(median(ages) * 10) / 10 : null,
    }
  }
  return out
}

export function groupByColumn(cards, columns) {
  const out = {}
  for (const { key } of columns) out[key] = []
  for (const c of cards) if (out[c.column]) out[c.column].push(c)
  return out
}

/** Distinct sprint/module/owner values across an unfiltered card set, for filter dropdowns. */
export function deriveFilterOptions(cards) {
  return {
    sprints: [...new Set(cards.map((c) => c.sprint).filter(Boolean))].sort(),
    modules: [...new Set(cards.map((c) => c.module).filter(Boolean))].sort(),
    owners: [...new Set(cards.map((c) => c.owner).filter(Boolean))].sort(),
  }
}

/** Which card keys moved to a new column between two polls, for the highlight-on-move flash. */
export function movedCardKeys(previousCards, nextCards) {
  const prevByKey = new Map(previousCards.map((c) => [c.key, c.column]))
  const moved = new Set()
  for (const c of nextCards) {
    const prev = prevByKey.get(c.key)
    if (prev && prev !== c.column) moved.add(c.key)
  }
  return moved
}
