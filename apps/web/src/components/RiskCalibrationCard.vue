<script setup>
// How well the PR risk score separates the PRs that went on to cause incidents: precision and
// recall at each tier threshold, and the blueprint's two bars. Loads on its own (scoring every
// merged PR takes a second or so) so the rest of the page doesn't wait for it.
import { onMounted, ref } from 'vue'
import { getOrchJson } from '../api'

const report = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    report.value = await getOrchJson('/api/v1/signals/calibration')
  } catch (err) {
    error.value = err.message
  }
})

const pct = (x) => `${(x * 100).toFixed(1)}%`

const headers = [
  { title: 'Flag PRs at', key: 'tier' },
  { title: 'PRs flagged', key: 'flagged', align: 'end' },
  { title: 'Precision', key: 'precision', align: 'end' },
  { title: 'Recall', key: 'recall', align: 'end' },
]

function rows(r) {
  return Object.entries(r.thresholds).map(([tier, t]) => ({ tier: `${tier} and above`, ...t }))
}
</script>

<template>
  <v-card class="h-100">
    <v-card-title class="pt-4">How well the risk score predicts incidents</v-card-title>
    <v-card-subtitle>
      Every merged PR scored as it would have been, then checked against what happened
    </v-card-subtitle>
    <v-alert v-if="error" type="warning" variant="tonal" density="compact" class="ma-4">
      {{ error }}
    </v-alert>
    <v-progress-linear v-else-if="!report" indeterminate color="secondary" class="ma-4" />
    <template v-else>
      <v-data-table
        :headers="headers"
        :items="rows(report)"
        hide-default-footer
        density="comfortable"
      >
        <template #[`item.precision`]="{ item }">{{ pct(item.precision) }}</template>
        <template #[`item.recall`]="{ item }">{{ pct(item.recall) }}</template>
      </v-data-table>
      <div class="px-4 pb-4 text-body-2">
        <p class="note mb-3">
          <strong>Precision</strong>: of the PRs flagged, the share that caused an incident.
          <strong>Recall</strong>: of the PRs that caused one, the share flagged. Higher tiers
          flag fewer PRs, more precisely, but miss more.
        </p>
        <div class="d-flex align-center ga-2 mb-1">
          <v-icon
            :icon="report.bars.t0_has_no_incidents ? 'mdi-check-circle' : 'mdi-close-circle'"
            :color="report.bars.t0_has_no_incidents ? 'success' : 'error'"
            size="18"
          />
          No incident PR in the T0 (automatic) band:
          {{ report.by_tier.T0.incidents }} of {{ report.by_tier.T0.prs }}
        </div>
        <div class="d-flex align-center ga-2 mb-3">
          <v-icon
            :icon="report.bars.top_decile_captures_majority ? 'mdi-check-circle' : 'mdi-close-circle'"
            :color="report.bars.top_decile_captures_majority ? 'success' : 'error'"
            size="18"
          />
          The riskiest 10% catch most incident PRs:
          {{ report.top_decile.incidents_captured }} of {{ report.incident_prs }}
        </div>
        <p class="note mb-0">
          {{ report.merged_prs }} merged PRs, {{ report.incident_prs }} of which caused an
          incident; {{ report.real_merged_prs }} are real GitHub PRs and the rest simulated. One
          history this small is a noisy judge (the riskiest 10% caught anywhere from 27% to 86%
          of incidents depending only on the random draw), so the bars are graded on 30 pooled
          histories with <code>python -m sdlc.risk calibrate --generated 30</code>, where both
          pass and a test locks them. The simulated incidents come from the same factors the score
          reads, so this proves the wiring, not that the score predicts real incidents.
        </p>
      </div>
    </template>
  </v-card>
</template>

<style scoped>
.note {
  font-size: 12px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}
</style>
