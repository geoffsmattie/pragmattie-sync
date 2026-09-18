<script setup>
import { onMounted } from 'vue'
import { useHealthStore } from '../stores/health'

const health = useHealthStore()
onMounted(() => health.check())

const phases = [
  { n: 1, title: 'Foundation', done: true },
  { n: 2, title: 'The CRM' },
  { n: 3, title: 'Signals + synthetic history' },
  { n: 4, title: 'First agents: triage + PR risk' },
  { n: 5, title: 'Forecasting' },
  { n: 6, title: 'Polish + client demo' },
]
</script>

<template>
  <v-container class="py-8" max-width="960">
    <h1 class="text-h4 mb-2">Welcome to SyncVista</h1>
    <p class="text-body-1 text-medium-emphasis mb-6">
      A CRM for mid-market B2B sales teams, and a live testbed for predictive, agent-driven
      software delivery.
    </p>

    <v-row>
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
