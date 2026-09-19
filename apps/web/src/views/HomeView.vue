<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'
import { money } from '../format'
import { useHealthStore } from '../stores/health'

const health = useHealthStore()
const summary = ref(null)
const summaryError = ref('')

onMounted(async () => {
  health.check()
  try {
    summary.value = await getJson('/api/v1/summary')
  } catch (err) {
    summaryError.value = err.message
  }
})

const phases = [
  { n: 1, title: 'Foundation', done: true },
  { n: 2, title: 'The CRM', done: true },
  { n: 3, title: 'Signals + synthetic history' },
  { n: 4, title: 'First agents: triage + PR risk' },
  { n: 5, title: 'Forecasting' },
  { n: 6, title: 'Polish + client demo' },
]
</script>

<template>
  <v-container class="py-8" max-width="1100">
    <h1 class="page-title mb-2">Welcome to PragMattie Sync</h1>
    <p class="text-body-1 text-medium-emphasis mb-6">
      A CRM for mid-market B2B sales teams, and a live testbed for predictive, agent-driven
      software delivery.
    </p>

    <v-alert v-if="summaryError" type="warning" variant="tonal" class="mb-4">
      Couldn't load the sales summary: {{ summaryError }}
    </v-alert>
    <v-row v-if="summary">
      <v-col
        v-for="tile in [
          { label: 'Open leads', value: summary.open_leads.toLocaleString(), to: '/leads', icon: 'mdi-account-plus-outline' },
          { label: 'Open deals', value: summary.open_deals.toLocaleString(), to: '/pipeline', icon: 'mdi-view-column-outline' },
          { label: 'Open pipeline', value: money(summary.open_pipeline), to: '/pipeline', icon: 'mdi-cash-multiple' },
          { label: `Won in ${summary.quarter}`, value: money(summary.won_this_quarter), to: '/forecast', icon: 'mdi-trophy-outline' },
        ]"
        :key="tile.label"
        cols="12"
        sm="6"
        md="3"
      >
        <v-card :to="tile.to" class="pa-4" hover>
          <div class="d-flex align-center ga-2 text-body-2 text-medium-emphasis">
            <v-icon :icon="tile.icon" size="18" />{{ tile.label }}
          </div>
          <div class="kpi-value mt-2">{{ tile.value }}</div>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-2">
      <v-col cols="12" md="6">
        <v-card title="System status" prepend-icon="mdi-heart-pulse">
          <v-card-text>
            <div class="d-flex align-center ga-2 mb-2">
              API
              <v-chip :color="health.status === 'ok' ? 'success' : 'error'" size="small">
                {{ health.loading ? 'checking…' : health.status }}
              </v-chip>
            </div>
            <div class="d-flex align-center ga-2">
              Database
              <v-chip :color="health.database === 'ok' ? 'success' : 'error'" size="small">
                {{ health.loading ? 'checking…' : health.database }}
              </v-chip>
            </div>
            <p v-if="health.error" class="text-error text-body-2 mt-3">{{ health.error }}</p>
          </v-card-text>
          <v-card-actions>
            <v-btn color="secondary" variant="tonal" @click="health.check()">Check again</v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card title="Build roadmap" prepend-icon="mdi-map-outline">
          <v-list density="compact">
            <v-list-item
              v-for="p in phases"
              :key="p.n"
              :title="`Phase ${p.n}: ${p.title}`"
              :prepend-icon="p.done ? 'mdi-check-circle' : 'mdi-circle-outline'"
              :base-color="p.done ? 'secondary' : undefined"
            />
          </v-list>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.page-title {
  font-size: 30px;
  font-weight: 700;
}
</style>
