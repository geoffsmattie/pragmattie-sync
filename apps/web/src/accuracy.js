// Pure helpers behind the Accuracy page (orchestrator/sdlc/accuracy.py builds the numbers), kept
// out of the view so they're unit-testable without mounting it.

export const pct = (x) => (x == null ? '—' : `${Math.round(x * 100)}%`)

export const shortSprint = (name) => name.replace('Sprint ', 'S')

/** A real-data trend's state: enough to draw, a few points so far, or nothing yet. */
export function realState(trend, minPoints) {
  if (!trend || trend.total === 0) return 'empty'
  return trend.total >= minPoints ? 'enough' : 'thin'
}

/** The four headline numbers, each with its target (if it has one) and whether it's simulated. */
export function headlines(report) {
  const { forecast, risk, triage, test_selector: selector } = report
  return [
    {
      key: 'forecast',
      title: 'Forecasts met by P85',
      value: pct(forecast.p85_hit_rate),
      target: `target ${pct(forecast.targets.p85_hit_rate)}`,
      detail: `${forecast.graded} sprints backtested`,
      simulated: true,
    },
    {
      key: 'risk',
      title: 'Incident PRs flagged T2+',
      value: pct(risk.recall),
      target: `${risk.caught} of ${risk.incident_prs}`,
      detail: `${risk.t0_incidents} incident PR(s) scored T0`,
      simulated: true,
    },
    {
      key: 'triage',
      title: 'Triage labels kept',
      value: pct(triage.kept_rate),
      target: `${triage.corrected} corrected`,
      detail: `${triage.total} real issues labelled`,
      simulated: false,
    },
    {
      key: 'selector',
      title: 'Test selector misses',
      value: selector.total ? `${selector.missed}` : '—',
      target: `of ${selector.total} real commits`,
      detail: 'a job it would have skipped failed',
      simulated: false,
    },
  ]
}
