<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getOrchJson } from '../api'
import ForecastTrail from '../components/forecast/ForecastTrail.vue'
import PlannerProposal from '../components/forecast/PlannerProposal.vue'
import PageHeader from '../components/PageHeader.vue'
import { MODULE_LABELS } from '../constants'
import {
  changedSubjects,
  dayLabel,
  mixLabel,
  onTimeTone,
  perWeek,
  shiftLabel,
  shiftTone,
} from '../forecast'

const POLL_MS = 15_000
// Mirrors orchestrator/sdlc/agents/planner.py's SLIP_BELOW: P85 past the sprint's last day.
const SLIP_BELOW = 0.85

const data = ref(null)
const loading = ref(true)
const error = ref('')
const flashing = ref(new Set())
let pollTimer = null

async function load() {
  try {
    const next = await getOrchJson('/api/v1/signals/forecast')
    const changed = changedSubjects(data.value, next)
    data.value = next
    if (changed.size) {
      flashing.value = changed
      setTimeout(() => {
        flashing.value = new Set()
      }, 2400)
    }
    error.value = ''
  } catch (err) {
    error.value = `${err.message}. Is the orchestrator service running on port 8001?`
  } finally {
    loading.value = false
  }
}

function savedAt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function pct(p) {
  return `${Math.round(p * 100)}%`
}

onMounted(() => {
  load()
  pollTimer = setInterval(load, POLL_MS)
})
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader
      title="Delivery forecast"
      subtitle="When the current sprint and each epic will likely land, from 10,000 simulated futures of the team's own recent pace."
    />

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="secondary" class="mb-4" />

    <v-alert
      v-if="data && !data.sprint && !data.epics.length"
      type="info"
      variant="tonal"
      class="mb-4"
    >
      No forecasts saved yet. The forecaster agent saves them from the agent loop
      (<code>docker compose --profile agents up -d</code>), or run
      <code>docker compose exec orchestrator python -m sdlc.forecaster now</code> once.
    </v-alert>

    <template v-if="data">
      <!-- The sprint -->
      <v-card
        v-if="data.sprint"
        variant="outlined"
        class="pa-5 mb-6 forecast-card"
        :class="{ 'forecast-card--moved': flashing.has(data.sprint.subject) }"
      >
        <div class="d-flex align-center flex-wrap ga-2 mb-4">
          <v-icon icon="mdi-flask-outline" size="16" class="text-medium-emphasis" title="Simulated" />
          <h2 class="section-title">{{ data.sprint.subject }}</h2>
          <span class="text-body-2 text-medium-emphasis">
            ends {{ dayLabel(data.sprint.end_date) }} · {{ mixLabel(data.sprint) }},
            {{ data.sprint.remaining_points }} points
          </span>
          <v-spacer />
          <v-chip
            :color="onTimeTone(data.sprint.on_time_probability)"
            variant="flat"
            size="small"
          >
            {{ pct(data.sprint.on_time_probability) }} chance on time
          </v-chip>
        </div>

        <div class="figures">
          <div>
            <div class="figure-label">Likely (P50)</div>
            <div class="figure">{{ dayLabel(data.sprint.p50) }}</div>
            <v-chip
              v-if="shiftLabel(data.sprint.moved.p50_days)"
              :color="shiftTone(data.sprint.moved.p50_days)"
              size="x-small"
              variant="tonal"
              class="mt-1"
            >
              {{ shiftLabel(data.sprint.moved.p50_days) }}
            </v-chip>
          </div>
          <div>
            <div class="figure-label">Safe to promise (P85)</div>
            <div class="figure">{{ dayLabel(data.sprint.p85) }}</div>
            <v-chip
              v-if="shiftLabel(data.sprint.moved.p85_days)"
              :color="shiftTone(data.sprint.moved.p85_days)"
              size="x-small"
              variant="tonal"
              class="mt-1"
            >
              {{ shiftLabel(data.sprint.moved.p85_days) }}
            </v-chip>
          </div>
          <div>
            <div class="figure-label">Team pace</div>
            <div class="figure">{{ perWeek(data.sprint.throughput_mean) }}<small> issues/week</small></div>
          </div>
          <div>
            <div class="figure-label">How it has moved</div>
            <ForecastTrail :trail="data.sprint.trail" />
          </div>
        </div>

        <div class="mt-5">
          <div class="figure-label mb-2">
            At risk ({{ data.sprint.at_risk.length }})
          </div>
          <p v-if="!data.sprint.at_risk.length" class="text-body-2 text-medium-emphasis">
            Every open item still fits in the time left, going by how long its kind of work has
            taken before.
          </p>
          <div v-for="item in data.sprint.at_risk" :key="item.number" class="risk-row">
            <v-chip size="x-small" variant="tonal" density="compact" class="flex-shrink-0">
              #{{ item.number }}
            </v-chip>
            <div>
              <div class="text-body-2 font-weight-medium">
                {{ item.title }}
                <span class="text-medium-emphasis font-weight-regular">
                  · {{ MODULE_LABELS[item.module] ?? item.module }} · {{ item.points }}pt
                </span>
              </div>
              <div class="text-body-2 text-medium-emphasis">{{ item.reason }}</div>
            </div>
          </div>
        </div>

        <PlannerProposal
          :proposal="data.sprint.proposal"
          :slipping="data.sprint.remaining_items > 0 && data.sprint.on_time_probability < SLIP_BELOW"
        />
      </v-card>

      <!-- The epics -->
      <h2 v-if="data.epics.length" class="section-title mb-3">Epics</h2>
      <div class="epic-grid">
        <v-card
          v-for="epic in data.epics"
          :key="epic.subject"
          variant="outlined"
          class="pa-4 forecast-card"
          :class="{ 'forecast-card--moved': flashing.has(epic.subject) }"
        >
          <div class="d-flex align-center ga-2 mb-1">
            <v-icon
              :icon="epic.remaining_real ? 'mdi-github' : 'mdi-flask-outline'"
              size="14"
              class="text-medium-emphasis"
              :title="epic.remaining_real ? 'Includes real GitHub stories' : 'Simulated'"
            />
            <h3 class="epic-title">{{ epic.subject }}</h3>
          </div>
          <div class="text-caption text-medium-emphasis mb-3">
            {{ mixLabel(epic) }} · {{ epic.remaining_points }} points · closing about
            {{ perWeek(epic.throughput_mean) }} a week
          </div>

          <div class="d-flex ga-6 mb-2">
            <div>
              <div class="figure-label">P50</div>
              <div class="figure figure--small">{{ dayLabel(epic.p50) }}</div>
            </div>
            <div>
              <div class="figure-label">P85</div>
              <div class="figure figure--small">{{ dayLabel(epic.p85) }}</div>
            </div>
          </div>

          <div v-if="shiftLabel(epic.moved.p50_days)" class="d-flex align-center flex-wrap ga-1 mb-2">
            <v-chip :color="shiftTone(epic.moved.p50_days)" size="x-small" variant="tonal">
              P50 {{ shiftLabel(epic.moved.p50_days) }}
            </v-chip>
            <span class="text-caption text-medium-emphasis">
              was {{ dayLabel(epic.moved.previous_p50) }}, {{ savedAt(epic.moved.previous_at) }}
            </span>
          </div>

          <ForecastTrail :trail="epic.trail" />
          <div class="text-caption text-medium-emphasis mt-1">
            Saved {{ savedAt(epic.created_at) }} ({{ epic.trigger }})
          </div>
        </v-card>
      </div>

      <p v-if="data.sprint || data.epics.length" class="text-caption text-medium-emphasis mt-6 method">
        How this works: each forecast replays the last {{ (data.sprint ?? data.epics[0]).history_days }}
        working days of real throughput (issues closed per day, or an epic's own stories)
        {{ (data.sprint ?? data.epics[0]).runs.toLocaleString() }} times. P50 is the date half of
        those futures beat; P85 is the date to promise. The same inputs on the same day always
        give the same answer. A forecast is saved when its inputs change, so the trail shows every
        time a date moved and why it's on this page, not a guess. The sprint is simulated history;
        each epic says how many of its open stories are real GitHub issues.
      </p>
    </template>
  </v-container>
</template>

<style scoped>
.section-title {
  font-size: 18px;
  font-weight: 700;
}
.epic-title {
  font-size: 15px;
  font-weight: 600;
}
.figures {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 20px;
}
.figure-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}
.figure {
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.figure small {
  font-size: 13px;
  font-weight: 500;
}
.figure--small {
  font-size: 17px;
}
.risk-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 8px 0;
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.epic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.forecast-card {
  background: rgb(var(--v-theme-surface));
}
.forecast-card--moved {
  animation: forecast-flash 2.4s ease;
}
@keyframes forecast-flash {
  0% {
    box-shadow: 0 0 0 3px #e8b35a;
  }
  100% {
    box-shadow: none;
  }
}
.method {
  max-width: 80ch;
}
@media (prefers-reduced-motion: reduce) {
  .forecast-card--moved {
    animation: none;
  }
}
</style>
