import { describe, expect, it } from 'vitest'
import { statusColor, subjectLabel } from '../src/decisions'

describe('subjectLabel', () => {
  it('labels an issue subject', () => {
    expect(subjectLabel({ subject_type: 'issue', subject_id: 12 })).toBe('Issue #12')
  })

  it('labels a PR subject', () => {
    expect(subjectLabel({ subject_type: 'pr', subject_id: 45 })).toBe('PR #45')
  })
})

describe('statusColor', () => {
  it('maps known statuses', () => {
    expect(statusColor('ok')).toBe('success')
    expect(statusColor('error')).toBe('error')
  })

  it('falls back for an unknown status', () => {
    expect(statusColor('pending')).toBe('default')
  })
})
