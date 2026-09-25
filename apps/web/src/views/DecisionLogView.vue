<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { getOrchJson, orchErrorMessage } from '../api'
import DecisionDetailDrawer from '../components/decisions/DecisionDetailDrawer.vue'
import PageHeader from '../components/PageHeader.vue'
import { TIER_COLORS } from '../constants'
import { statusColor, subjectLabel } from '../decisions'

const POLL_MS = 15_000

const decisions = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const selected = ref(null)

const filters = reactive({ agent: '', status: '', subject_type: '', tier: '' })
const page = ref(1)
const itemsPerPage = ref(25)

const headers = [
  { title: 'Time', key: 'created_at', width: 170 },
  { title: 'Agent', key: 'agent', width: 100 },
  { title: 'Subject', key: 'subject', width: 110 },
  { title: 'Tier', key: 'tier', width: 80 },
  { title: 'Score', key: 'final_score', width: 80, align: 'end' },
  { title: 'Status', key: 'status', width: 100 },
  { title: 'Trigger', key: 'trigger', width: 100 },
  { title: 'Latency', key: 'latency_ms', width: 90, align: 'end' },
]

let pollTimer = null

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

async function load() {
  try {
    const data = await getOrchJson('/api/v1/signals/decisions', {
      agent: filters.agent,
      status: filters.status,
      subject_type: filters.subject_type,
      tier: filters.tier,
      limit: itemsPerPage.value,
      offset: (page.value - 1) * itemsPerPage.value,
    })
    decisions.value = data.decisions
    total.value = data.total
    error.value = ''
  } catch (err) {
    error.value = orchErrorMessage(err)
  } finally {
    loading.value = false
  }
}

function onOptionsUpdate({ page: p, itemsPerPage: n }) {
  page.value = p
  itemsPerPage.value = n
  load()
}

function onFilterChange() {
  page.value = 1
  load()
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
      title="Decision log"
      subtitle="The full audit trail: every agent run, its inputs, its score, and what it did about it."
    >
      <div class="d-flex align-center flex-wrap ga-2">
        <v-select
          v-model="filters.agent"
          :items="[
            { title: 'All agents', value: '' },
            { title: 'PR risk', value: 'pr_risk' },
            { title: 'Triage', value: 'triage' },
            { title: 'Forecaster', value: 'forecaster' },
            { title: 'Planner', value: 'planner' },
            { title: 'Test selector', value: 'test_selector' },
            { title: 'Tier overrides', value: 'tier_override' },
            { title: 'Release gate', value: 'release_gate' },
          ]"
          label="Agent"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 140px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.subject_type"
          :items="[
            { title: 'All subjects', value: '' },
            { title: 'Pull requests', value: 'pr' },
            { title: 'Issues', value: 'issue' },
            { title: 'Sprints', value: 'sprint' },
            { title: 'Epics', value: 'epic' },
            { title: 'Releases', value: 'release' },
          ]"
          label="Subject"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.status"
          :items="[
            { title: 'All statuses', value: '' },
            { title: 'OK', value: 'ok' },
            { title: 'Error', value: 'error' },
            { title: 'Rejected', value: 'rejected' },
            { title: 'Missed', value: 'missed' },
          ]"
          label="Status"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 130px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.tier"
          :items="[
            { title: 'All tiers', value: '' },
            { title: 'T0', value: 'T0' },
            { title: 'T1', value: 'T1' },
            { title: 'T2', value: 'T2' },
            { title: 'T3', value: 'T3' },
          ]"
          label="Tier"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 110px"
          @update:model-value="onFilterChange"
        />
      </div>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>

    <v-card>
      <v-data-table-server
        v-model:page="page"
        v-model:items-per-page="itemsPerPage"
        :headers="headers"
        :items="decisions"
        :items-length="total"
        :loading="loading"
        density="comfortable"
        items-per-page-text="Rows per page"
        @update:options="onOptionsUpdate"
        @click:row="(_, { item }) => (selected = item)"
      >
        <template #[`item.created_at`]="{ item }">{{ fmt(item.created_at) }}</template>
        <template #[`item.subject`]="{ item }">{{ subjectLabel(item) }}</template>
        <template #[`item.tier`]="{ item }">
          <v-chip
            v-if="item.tier"
            size="x-small"
            :color="TIER_COLORS[item.tier] ?? 'default'"
            variant="flat"
          >
            {{ item.tier }}
          </v-chip>
          <span v-else class="text-medium-emphasis">—</span>
        </template>
        <template #[`item.final_score`]="{ item }">{{ item.final_score ?? '—' }}</template>
        <template #[`item.status`]="{ item }">
          <v-chip size="x-small" :color="statusColor(item.status)" variant="tonal">
            {{ item.status }}
          </v-chip>
        </template>
        <template #[`item.latency_ms`]="{ item }">
          {{ item.latency_ms != null ? `${item.latency_ms}ms` : '—' }}
        </template>
        <template #no-data>
          <div class="pa-6 text-center text-medium-emphasis">
            No agent decisions recorded yet for this filter.
          </div>
        </template>
      </v-data-table-server>
    </v-card>

    <DecisionDetailDrawer :decision="selected" @close="selected = null" />
  </v-container>
</template>

<style scoped>
:deep(tbody tr) {
  cursor: pointer;
}
</style>
