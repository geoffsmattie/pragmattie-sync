import { describe, expect, it } from 'vitest'
import {
  cardAtTime,
  columnStatsAt,
  deriveFilterOptions,
  groupByColumn,
  median,
  movedCardKeys,
  releaseChip,
} from '../src/board'

const COLUMNS = [
  { key: 'backlog', title: 'Backlog' },
  { key: 'triaged', title: 'Triaged' },
  { key: 'in_progress', title: 'In progress' },
]

function card(overrides) {
  return {
    key: 'issue-1',
    source: 'synthetic',
    issue_number: 1,
    pr_number: null,
    title: 'Fix lead import',
    module: 'leads',
    points: 1,
    owner: 'Tomas R.',
    sprint: 'Sprint 1',
    column: 'triaged',
    entered_column_at: '2026-03-27T09:18:00',
    tier: null,
    risk_score: null,
    gate_missing: [],
    rolled_back: false,
    decisions: [],
    transitions: [
      ['backlog', '2026-03-20T09:00:00'],
      ['triaged', '2026-03-27T09:18:00'],
    ],
    ...overrides,
  }
}

describe('cardAtTime', () => {
  it('returns the column that was current as of a point in time', () => {
    const c = card()
    expect(cardAtTime(c, new Date('2026-03-22T00:00:00')).column).toBe('backlog')
    expect(cardAtTime(c, new Date('2026-04-01T00:00:00')).column).toBe('triaged')
  })

  it('returns null before the card enters the pipeline', () => {
    const c = card()
    expect(cardAtTime(c, new Date('2026-01-01T00:00:00'))).toBeNull()
  })

  it('does not mutate the source card', () => {
    const c = card()
    cardAtTime(c, new Date('2026-03-22T00:00:00'))
    expect(c.column).toBe('triaged')
  })
})

describe('median', () => {
  it('returns null for an empty list', () => {
    expect(median([])).toBeNull()
  })

  it('averages the two middle values for an even count', () => {
    expect(median([1, 3])).toBe(2)
  })

  it('picks the middle value for an odd count, unsorted input', () => {
    expect(median([5, 1, 3])).toBe(3)
  })
})

describe('groupByColumn', () => {
  it('buckets cards by column and includes empty columns', () => {
    const cards = [card({ key: 'issue-1', column: 'backlog' }), card({ key: 'issue-2', column: 'backlog' })]
    const grouped = groupByColumn(cards, COLUMNS)
    expect(grouped.backlog).toHaveLength(2)
    expect(grouped.triaged).toEqual([])
    expect(grouped.in_progress).toEqual([])
  })

  it('drops cards whose column is not in the known set', () => {
    const grouped = groupByColumn([card({ column: 'production' })], COLUMNS)
    expect(Object.values(grouped).flat()).toHaveLength(0)
  })
})

describe('columnStatsAt', () => {
  it('computes WIP and median age per column as of a given instant', () => {
    const now = new Date('2026-03-29T09:18:00') // 2 days after entering triaged
    const stats = columnStatsAt([card({ column: 'triaged' })], now, COLUMNS)
    expect(stats.triaged.wip).toBe(1)
    expect(stats.triaged.median_age_hours).toBe(48)
    expect(stats.backlog.wip).toBe(0)
    expect(stats.backlog.median_age_hours).toBeNull()
  })
})

describe('deriveFilterOptions', () => {
  it('collects distinct, sorted, non-null values for each filter dimension', () => {
    const cards = [
      card({ sprint: 'Sprint 2', module: 'leads', owner: 'Bea N.' }),
      card({ sprint: 'Sprint 1', module: 'billing_auth', owner: null }),
      card({ sprint: null, module: 'leads', owner: 'Bea N.' }),
    ]
    expect(deriveFilterOptions(cards)).toEqual({
      sprints: ['Sprint 1', 'Sprint 2'],
      modules: ['billing_auth', 'leads'],
      owners: ['Bea N.'],
    })
  })
})

describe('movedCardKeys', () => {
  it('flags only cards whose column changed between two polls', () => {
    const before = [card({ key: 'issue-1', column: 'triaged' }), card({ key: 'issue-2', column: 'backlog' })]
    const after = [card({ key: 'issue-1', column: 'in_progress' }), card({ key: 'issue-2', column: 'backlog' })]
    expect(movedCardKeys(before, after)).toEqual(new Set(['issue-1']))
  })

  it('does not flag a card seen for the first time', () => {
    const after = [card({ key: 'issue-3', column: 'backlog' })]
    expect(movedCardKeys([], after)).toEqual(new Set())
  })
})

describe('releaseChip', () => {
  const release = (verdict) => ({
    verdict,
    description: 'T2 · Held: open incident in pipeline (#61)',
    reasons: ['open incident in pipeline (#61)'],
  })

  it('shows a merged card held, blocked or releasing', () => {
    const held = releaseChip(card({ column: 'merged', release: release('hold') }))
    expect(held).toEqual({
      text: 'Release held',
      color: 'warning',
      title: 'T2 · Held: open incident in pipeline (#61)',
    })
    expect(releaseChip(card({ column: 'merged', release: release('blocked') })).color).toBe('error')
    expect(releaseChip(card({ column: 'merged', release: release('release') })).text).toBe(
      'Releasing',
    )
  })

  it('shows nothing without a verdict or outside Merged', () => {
    expect(releaseChip(card({ column: 'merged', release: null }))).toBeNull()
    expect(releaseChip(card({ column: 'production', release: release('hold') }))).toBeNull()
  })
})
