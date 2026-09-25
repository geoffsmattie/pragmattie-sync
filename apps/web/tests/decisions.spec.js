import { describe, expect, it } from 'vitest'
import { statusColor, subjectLabel } from '../src/decisions'

describe('subjectLabel', () => {
  it('labels an issue subject', () => {
    expect(subjectLabel({ subject_type: 'issue', subject_id: 12 })).toBe('Issue #12')
  })

  it('labels a PR subject', () => {
    expect(subjectLabel({ subject_type: 'pr', subject_id: 45 })).toBe('PR #45')
  })

  it('labels a release by the newest PR in it', () => {
    expect(subjectLabel({ subject_type: 'release', subject_id: 61 })).toBe('Release up to PR #61')
    expect(subjectLabel({ subject_type: 'release', subject_id: 0 })).toBe('Release')
  })

  it('labels a forecast by the sprint or epic it forecasts', () => {
    const sprint = { subject_type: 'sprint', subject_id: 3, output: { subject: 'Sprint 13' } }
    expect(subjectLabel(sprint)).toBe('Sprint: Sprint 13')
    const epic = { subject_type: 'epic', subject_id: 4, output: { subject: 'Salesforce import' } }
    expect(subjectLabel(epic)).toBe('Epic: Salesforce import')
    expect(subjectLabel({ subject_type: 'epic', subject_id: 9 })).toBe('Epic: forecast #9')
  })
})

describe('statusColor', () => {
  it('maps known statuses', () => {
    expect(statusColor('ok')).toBe('success')
    expect(statusColor('rejected')).toBe('warning')
    expect(statusColor('error')).toBe('error')
    expect(statusColor('missed')).toBe('warning')
  })

  it('falls back for an unknown status', () => {
    expect(statusColor('pending')).toBe('default')
  })
})
