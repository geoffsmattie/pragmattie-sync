<script setup>
import { computed, onMounted, ref } from 'vue'
import { getOrchJson } from '../api'
import CycleTimeChart from '../components/charts/CycleTimeChart.vue'
import VelocityChart from '../components/charts/VelocityChart.vue'
import PageHeader from '../components/PageHeader.vue'
import { MODULE_LABELS } from '../constants'

const summary = ref(null)
const sprints = ref([])
const cycle = ref([])
const ci = ref(null)
const modules = ref([])
const sources = ref(null)
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const [s, sp, ct, c, m, src] = await Promise.all([
      getOrchJson('/api/v1/signals/summary', { days: 30 }),
      getOrchJson('/api/v1/signals/sprints'),
      getOrchJson('/api/v1/signals/cycle-time', { bucket: 'sprint' }),
      getOrchJson('/api/v1/signals/ci', { weeks: 26 }),
      getOrchJson('/api/v1/signals/modules'),
      getOrchJson('/api/v1/signals/sources'),
    ])
    summary.value = s
    sprints.value = sp
    cycle.value = ct
    ci.value = c
    modules.value = m
    sources.value = src
  } catch (err) {
    error.value = `${err.message}. Is the orchestrator service running on port 8001?`
  } finally {
    loading.value = false
  }
})

// DORA measures. `better` says which direction is good, so deltas get the right color.
const DORA = [
  { key: 'deploys_per_week', label: 'Deployment frequency', unit: '/wk', better: 'up' },
  { key: 'lead_time_hours', label: 'Lead time for changes', unit: 'h', better: 'down', note: 'PR opened → merged, median' },
  { key: 'change_failure_rate', label: 'Change failure rate', unit: '%', better: 'down' },
  { key: 'time_to_restore_hours', label: 'Time to restore', unit: 'h', better: 'down', note: 'median' },
]

const tiles = computed(() => {
  if (!summary.value) return []
  const { current, previous } = summary.value
  return DORA.map((d) => {
    const now = current[d.key]
    const before = previous[d.key]
    let delta = null
    if (now != null && before != null && before !== 0) {
      const change = now - before
      const improved = d.better === 'up' ? change > 0 : change < 0
      delta = {
        text: `${change > 0 ? '+' : ''}${Math.round(change * 10) / 10}${d.unit} vs prior 30 days`,
        tone: change === 0 ? 'neutral' : improved ? 'good' : 'bad',
        icon: change === 0 ? 'mdi-minus' : change > 0 ? 'mdi-arrow-up' : 'mdi-arrow-down',
      }
    }
    return { ...d, value: now == null ? '—' : `${now}${d.unit === '/wk' ? '' : d.unit}`, delta }
  })
})

const sourceNote = computed(() => {
  if (!sources.value) return ''
  const prs = sources.value.pull_requests ?? {}
  const synthetic = prs.synthetic ?? 0
  const live = prs.github ?? 0
  return live
    ? `${synthetic} simulated PRs of history plus ${live} real PRs collected from GitHub.`
    : `${synthetic} simulated PRs of history. Real GitHub activity appears here once the collector runs.`
})

const moduleHeaders = [
  { title: 'Module', key: 'module' },
  { title: 'Merged PRs', key: 'merged_prs', align: 'end' },
  { title: 'Incidents', key: 'incidents', align: 'end' },
  { title: 'Incident rate', key: 'incident_rate', align: 'end', width: 200 },
  { title: 'Days per story point', key: 'days_per_point', align: 'end' },
]
const maxRate = computed(() => Math.max(1, ...modules.value.map((m) => m.incident_rate)))
const medianDaysPerPoint = computed(() => {
  const v = modules.value.map((m) => m.days_per_point).filter((x) => x != null).sort((a, b) => a - b)
  return v.length ? v[Math.floor(v.length / 2)] : null
})

const suiteHeaders = [
  { title: 'Test suite', key: 'suite' },
  { title: 'Runs', key: 'runs', align: 'end' },
  { title: 'Pass rate', key: 'pass_rate', align: 'end' },
  { title: 'Flaky failures', key: 'flaky_rate', align: 'end' },
]
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader
      title="Engineering signals"
      subtitle="How the PragMattie Sync team delivers: the history the prediction models learn from."
    />

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="secondary" class="mb-4" />

    <v-alert v-if="sources" type="info" variant="tonal" density="compact" icon="mdi-flask-outline" class="mb-4">
      {{ sourceNote }}
    </v-alert>

    <template v-if="summary">
      <div class="text-body-2 text-medium-emphasis mb-2">Last 30 days · DORA delivery measures</div>
      <v-row>
        <v-col v-for="t in tiles" :key="t.key" cols="12" sm="6" md="3">
          <v-card class="pa-4 h-100">
            <div class="text-body-2 text-medium-emphasis">{{ t.label }}</div>
            <div class="kpi-value mt-1">{{ t.value }}<span v-if="t.unit === '/wk'" class="unit">per week</span></div>
            <div v-if="t.delta" class="delta mt-1" :class="t.delta.tone">
              <v-icon :icon="t.delta.icon" size="14" />{{ t.delta.text }}
            </div>
            <div v-if="t.note" class="note mt-1">{{ t.note }}</div>
          </v-card>
        </v-col>
      </v-row>
    </template>

    <v-row v-if="sprints.length" class="mt-2">
      <v-col cols="12" lg="6">
        <v-card class="pa-4 h-100">
          <div class="font-weight-medium mb-1">Sprint velocity</div>
          <div class="note mb-2">Story points committed vs completed by sprint end</div>
          <VelocityChart :sprints="sprints" />
        </v-card>
      </v-col>
      <v-col cols="12" lg="6">
        <v-card class="pa-4 h-100">
          <div class="font-weight-medium mb-1">Pull request cycle time</div>
          <div class="note mb-2">Hours from opened to merged, for PRs merged in each sprint</div>
          <CycleTimeChart :sprints="cycle" />
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="modules.length" class="mt-2">
      <v-col cols="12" lg="7">
        <v-card class="h-100">
          <v-card-title class="pt-4">Risk and effort by module</v-card-title>
          <v-card-subtitle>Incident rate = share of merged PRs that caused a production incident</v-card-subtitle>
          <v-data-table :headers="moduleHeaders" :items="modules" hide-default-footer items-per-page="-1" density="comfortable">
            <template #[`item.module`]="{ item }"><span class="text-no-wrap">{{ MODULE_LABELS[item.module] ?? item.module }}</span></template>
            <template #[`item.incident_rate`]="{ item }">
              <div class="d-flex align-center justify-end ga-2">
                <div class="rate-track"><div class="rate-bar" :style="{ width: `${(item.incident_rate / maxRate) * 100}%` }" /></div>
                <span style="width: 44px">{{ item.incident_rate }}%</span>
              </div>
            </template>
            <template #[`item.days_per_point`]="{ item }">
              <span :class="{ 'font-weight-bold': medianDaysPerPoint && item.days_per_point > medianDaysPerPoint * 1.3 }">
                {{ item.days_per_point ?? '—' }}
              </span>
              <v-icon
                v-if="medianDaysPerPoint && item.days_per_point > medianDaysPerPoint * 1.3"
                icon="mdi-alert-outline"
                size="16"
                color="warning"
                class="ml-1"
                title="Runs well over estimate compared with other modules"
              />
            </template>
          </v-data-table>
        </v-card>
      </v-col>
      <v-col cols="12" lg="5">
        <v-card v-if="ci" class="h-100">
          <v-card-title class="pt-4">CI health</v-card-title>
          <v-card-subtitle>Last 26 weeks · flaky = failed, then passed on re-run</v-card-subtitle>
          <v-data-table :headers="suiteHeaders" :items="ci.by_suite" hide-default-footer density="comfortable">
            <template #[`item.pass_rate`]="{ item }">{{ item.pass_rate }}%</template>
            <template #[`item.flaky_rate`]="{ item }">
              <span :class="{ 'font-weight-bold': item.flaky_rate >= 3 }">{{ item.flaky_rate }}%</span>
              <v-icon v-if="item.flaky_rate >= 3" icon="mdi-alert-outline" size="16" color="warning" class="ml-1" title="Flaky suite" />
            </template>
          </v-data-table>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.note {
  font-size: 12px;
  color: #5b6573;
}
.unit {
  font-size: 14px;
  font-weight: 500;
  color: #5b6573;
  margin-left: 6px;
}
.delta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #5b6573;
}
.delta.good .v-icon {
  color: rgb(var(--v-theme-success));
}
.delta.bad .v-icon {
  color: rgb(var(--v-theme-error));
}
.rate-track {
  width: 100px;
  height: 8px;
  border-radius: 4px;
  background: #eef1f3;
}
.rate-bar {
  height: 8px;
  border-radius: 4px;
  background: #1b8a94;
}
</style>
