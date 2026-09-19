export const STAGES = [
  { value: 'prospecting', title: 'Prospecting', probability: 10 },
  { value: 'qualification', title: 'Qualification', probability: 25 },
  { value: 'proposal', title: 'Proposal', probability: 50 },
  { value: 'negotiation', title: 'Negotiation', probability: 75 },
  { value: 'closed_won', title: 'Closed won', probability: 100 },
  { value: 'closed_lost', title: 'Closed lost', probability: 0 },
]
export const OPEN_STAGES = STAGES.slice(0, 4)
export const stageTitle = (value) => STAGES.find((s) => s.value === value)?.title ?? value

export const LEAD_STATUSES = [
  { value: 'new', title: 'New', color: 'info', icon: 'mdi-star-four-points-outline' },
  { value: 'working', title: 'Working', color: 'secondary', icon: 'mdi-progress-clock' },
  { value: 'qualified', title: 'Qualified', color: 'success', icon: 'mdi-check-decagram-outline' },
  { value: 'disqualified', title: 'Disqualified', color: 'grey', icon: 'mdi-close-circle-outline' },
  { value: 'converted', title: 'Converted', color: 'primary', icon: 'mdi-swap-horizontal' },
]
export const leadStatus = (value) => LEAD_STATUSES.find((s) => s.value === value) ?? LEAD_STATUSES[0]

export const LEAD_SOURCES = [
  { value: 'web', title: 'Web' },
  { value: 'referral', title: 'Referral' },
  { value: 'event', title: 'Event' },
  { value: 'outbound', title: 'Outbound' },
  { value: 'partner', title: 'Partner' },
]

export const INDUSTRIES = [
  'Energy',
  'Financial Services',
  'Healthcare',
  'Life Sciences',
  'Manufacturing',
  'Professional Services',
  'Retail',
  'Technology',
  'Telecommunications',
  'Transportation',
]

export const REGIONS = ['North America East', 'North America West', 'North America Central', 'EMEA', 'APAC']

// Forecast chart colors: one teal ramp, darkest = most certain.
// Validated as an ordinal ramp (monotone lightness, light end clears 2:1 on white).
export const FORECAST_COLORS = {
  won: '#0E5A61',
  negotiation: '#1B8A94',
  proposal: '#6FBAC1',
}
