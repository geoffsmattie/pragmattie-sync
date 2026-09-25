<script setup>
import { computed, onMounted, ref } from 'vue'
import { headlines, pct, realState, shortSprint } from '../accuracy'
import { getOrchJson, orchErrorMessage } from '../api'
import HitRateChart from '../components/charts/HitRateChart.vue'
import StackedCountChart from '../components/charts/StackedCountChart.vue'
import PageHeader from '../components/PageHeader.vue'
import { ORDINAL_PAIR } from '../constants'

const MISS = '#E8B35A' // gold: the ones the prediction got wrong

const report = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    report.value = await getOrchJson('/api/v1/signals/accuracy')
  } catch (err) {
    error.value = orchErrorMessage(err)
  }
})

const tiles = computed(() => (report.value ? headlines(report.value) : []))
const minPoints = computed(() => report.value?.min_points ?? 5)

const riskSeries = computed(() => {
  const rows = report.value.risk.sprints
  return [
    { label: 'Flagged T2+', color: ORDINAL_PAIR.dark, data: rows.map((r) => r.caught) },
    { label: 'Missed', color: MISS, data: rows.map((r) => r.incident_prs - r.caught) },
  ]
})

function weekLabel(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const triageSeries = computed(() => {
  const weeks = report.value.triage.weeks
  return [
    { label: 'Kept', color: ORDINAL_PAIR.dark, data: weeks.map((w) => w.labelled - w.corrected) },
    { label: 'Corrected by a person', color: MISS, data: weeks.map((w) => w.corrected) },
  ]
})

const selectorSeries = computed(() => {
  const weeks = report.value.test_selector.weeks
  return [
    { label: 'Safe to skip', color: ORDINAL_PAIR.dark, data: weeks.map((w) => w.settled - w.missed) },
    { label: 'Missed', color: MISS, data: weeks.map((w) => w.missed) },
  ]
})

const lateLabel = (days) => (days === 0 ? 'on P50' : days > 0 ? `${days}d late` : `${-days}d early`)
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader
      title="Prediction accuracy"
      subtitle="How often the orchestrator's predictions matched what happened, and whether that is improving."
    />

    <v-alert v-if="error" type="warning" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-else-if="!report" indeterminate color="secondary" />

    <template v-else>
      <v-row class="mb-2">
        <v-col v-for="t in tiles" :key="t.key" cols="12" sm="6" lg="3">
          <v-card class="h-100 pa-4">
            <div class="d-flex align-center mb-2">
              <span class="text-body-2 text-medium-emphasis">{{ t.title }}</span>
              <v-spacer />
              <v-chip size="x-small" variant="tonal" :prepend-icon="t.simulated ? 'mdi-flask-outline' : 'mdi-github'">
                {{ t.simulated ? 'Simulated' : 'Real' }}
              </v-chip>
            </div>
            <div class="headline-value">{{ t.value }}</div>
            <div class="text-body-2">{{ t.target }}</div>
            <div class="text-caption text-medium-emphasis">{{ t.detail }}</div>
          </v-card>
        </v-col>
      </v-row>

      <v-row>
        <v-col cols="12" lg="6">
          <v-card class="h-100">
            <v-card-title class="pt-4">Delivery forecasts</v-card-title>
            <v-card-subtitle>
              Each finished sprint forecast again as of its working day {{ report.forecast.as_of_workday }},
              using only what was known then
            </v-card-subtitle>
            <div class="pa-4">
              <HitRateChart :sprints="report.forecast.sprints" :targets="report.forecast.targets" />
              <div class="d-flex flex-wrap ga-1 mt-3">
                <v-chip
                  v-for="s in report.forecast.sprints"
                  :key="s.sprint"
                  size="x-small"
                  variant="tonal"
                  :color="s.p85_met ? 'default' : 'warning'"
                  :title="`Forecast ${s.p50} (P50), ${s.p85} (P85); finished ${s.actual ?? 'not yet'}`"
                >
                  {{ shortSprint(s.sprint) }} · {{ s.p50_error_days == null ? 'unfinished' : lateLabel(s.p50_error_days) }}
                </v-chip>
              </div>
              <p class="note mt-3">
                A well-calibrated P85 is met about 85% of the time and a P50 about half the time.
                The chips show how far each sprint's finish landed from its P50: early sprints had
                little history behind them, so their forecasts were far too cautious, and the error
                shrinks as history builds up. Simulated history.
              </p>
            </div>
          </v-card>
        </v-col>

        <v-col cols="12" lg="6">
          <v-card class="h-100">
            <v-card-title class="pt-4">Risk score</v-card-title>
            <v-card-subtitle>
              PRs that went on to cause an incident, by sprint: did the score put them at T2 or above?
            </v-card-subtitle>
            <div class="pa-4">
              <StackedCountChart
                :labels="report.risk.sprints.map((s) => shortSprint(s.sprint))"
                :series="riskSeries"
                aria-label="Incident-causing PRs per sprint, flagged or missed by the risk score"
              />
              <p class="note mt-3">
                {{ report.risk.caught }} of {{ report.risk.incident_prs }} incident PRs flagged
                ({{ pct(report.risk.recall) }}); {{ report.risk.t0_incidents }} scored T0. Only a
                few incidents happen per sprint, so read the total, not one sprint. Simulated
                history. Real PRs so far: {{ report.risk.real.merged_prs }} merged,
                {{ report.risk.real.incident_prs }} caused an incident, so nothing real to grade yet.
              </p>
            </div>
          </v-card>
        </v-col>

        <v-col cols="12" lg="6">
          <v-card class="h-100">
            <v-card-title class="pt-4">Triage agent</v-card-title>
            <v-card-subtitle>Real issues it labelled, by week: kept as it set them, or changed by a person</v-card-subtitle>
            <div class="pa-4">
              <StackedCountChart
                v-if="realState(report.triage, minPoints) === 'enough'"
                :labels="report.triage.weeks.map((w) => weekLabel(w.week))"
                :series="triageSeries"
                aria-label="Issues the triage agent labelled per week, kept or corrected"
              />
              <p v-else class="text-body-2">
                {{ report.triage.total }} real issue(s) labelled so far: the trend appears at {{ minPoints }}.
              </p>
              <p class="note mt-3">
                Real issues only. Kept labels can echo labels an issue already had, so the stricter
                test is the blind evaluation against your own labels (<code>python -m sdlc.eval</code>).
              </p>
            </div>
          </v-card>
        </v-col>

        <v-col cols="12" lg="6">
          <v-card class="h-100">
            <v-card-title class="pt-4">Test selector</v-card-title>
            <v-card-subtitle>Real commits whose CI finished, by week: would skipping its picks have been safe?</v-card-subtitle>
            <div class="pa-4">
              <StackedCountChart
                v-if="realState(report.test_selector, minPoints) === 'enough'"
                :labels="report.test_selector.weeks.map((w) => weekLabel(w.week))"
                :series="selectorSeries"
                aria-label="Commits per week where skipping the selector's picks was safe or missed a failure"
              />
              <p v-else class="text-body-2">
                {{ report.test_selector.total }} real commit(s) settled so far: the trend appears at {{ minPoints }}.
              </p>
              <p class="note mt-3">
                Real PRs only. CI still runs every job, so each commit shows whether skipping would
                have been safe. A miss is a job it would have skipped that failed.
              </p>
            </div>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </v-container>
</template>

<style scoped>
.headline-value {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.2;
}
.note {
  font-size: 13px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  max-width: 68ch;
}
</style>
