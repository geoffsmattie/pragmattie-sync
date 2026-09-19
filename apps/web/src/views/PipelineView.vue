<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJson, sendJson } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { OPEN_STAGES, STAGES, stageTitle } from '../constants'
import { money, moneyFull, shortDate } from '../format'
import { quarterLabel, quarterOf, quarterRange, shiftQuarter } from '../quarters'
import { useRepsStore } from '../stores/reps'

const reps = useRepsStore()
const current = quarterOf()
const windows = [
  { value: 'this', title: `This quarter (${quarterLabel(current)})`, range: quarterRange(current) },
  { value: 'next', title: `Next quarter (${quarterLabel(shiftQuarter(current, 1))})`, range: quarterRange(shiftQuarter(current, 1)) },
  { value: 'all', title: 'All open deals', range: {} },
]
const windowValue = ref('this')
const owner = ref(null)
const opps = ref([])
const loading = ref(false)
const error = ref('')
const snack = ref('')

async function load() {
  loading.value = true
  error.value = ''
  const range = windows.find((w) => w.value === windowValue.value).range
  try {
    const data = await getJson('/api/v1/opportunities', {
      stage: OPEN_STAGES.map((s) => s.value),
      owner_id: owner.value,
      close_from: range.start,
      close_to: range.end,
      limit: 500,
    })
    opps.value = data.items
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
watch([windowValue, owner], load)
onMounted(() => {
  reps.load()
  load()
})

const columns = computed(() =>
  OPEN_STAGES.map((stage) => {
    const items = opps.value.filter((o) => o.stage === stage.value)
    return { ...stage, items, total: items.reduce((sum, o) => sum + Number(o.amount), 0) }
  }),
)
const grandTotal = computed(() => columns.value.reduce((sum, c) => sum + c.total, 0))
const weighted = computed(() =>
  opps.value.reduce((sum, o) => sum + (Number(o.amount) * o.probability) / 100, 0),
)

async function move(opp, stage) {
  try {
    await sendJson('PATCH', `/api/v1/opportunities/${opp.id}`, { stage })
    snack.value = `${opp.name} moved to ${stageTitle(stage)}`
    load()
  } catch (err) {
    error.value = err.message
  }
}
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader title="Pipeline" subtitle="Open opportunities by stage. Use a card's menu to move it forward.">
      <v-select v-model="windowValue" :items="windows" density="compact" hide-details style="min-width: 240px" />
      <v-select v-model="owner" :items="reps.options" label="Owner" density="compact" hide-details clearable style="min-width: 180px" />
    </PageHeader>

    <div class="d-flex ga-6 mb-4 text-body-2">
      <div><span class="text-medium-emphasis">Open pipeline</span> <strong class="ml-1">{{ moneyFull(grandTotal) }}</strong></div>
      <div><span class="text-medium-emphasis">Weighted</span> <strong class="ml-1">{{ moneyFull(weighted) }}</strong></div>
      <div><span class="text-medium-emphasis">Deals</span> <strong class="ml-1">{{ opps.length }}</strong></div>
    </div>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="secondary" class="mb-2" />

    <div class="board">
      <div v-for="col in columns" :key="col.value" class="board-column">
        <div class="d-flex align-baseline justify-space-between px-1 mb-2">
          <div class="font-weight-bold">{{ col.title }} <span class="text-medium-emphasis font-weight-regular">· {{ col.items.length }}</span></div>
          <div class="text-body-2">{{ money(col.total) }}</div>
        </div>
        <div class="text-caption text-medium-emphasis px-1 mb-2">{{ col.probability }}% win probability</div>
        <v-card v-for="opp in col.items" :key="opp.id" class="mb-2" variant="outlined">
          <v-card-text class="pa-3">
            <div class="d-flex justify-space-between align-start ga-2">
              <router-link :to="{ name: 'account', params: { id: opp.account.id } }" class="text-body-2 font-weight-medium opp-link">
                {{ opp.name }}
              </router-link>
              <v-menu>
                <template #activator="{ props }">
                  <v-btn v-bind="props" icon="mdi-dots-vertical" size="x-small" variant="text" aria-label="Move opportunity" />
                </template>
                <v-list density="compact">
                  <v-list-subheader>Move to</v-list-subheader>
                  <v-list-item
                    v-for="s in STAGES.filter((x) => x.value !== opp.stage)"
                    :key="s.value"
                    :title="s.title"
                    @click="move(opp, s.value)"
                  />
                </v-list>
              </v-menu>
            </div>
            <div class="d-flex justify-space-between mt-2 text-body-2">
              <strong>{{ moneyFull(opp.amount) }}</strong>
              <span class="text-medium-emphasis">{{ shortDate(opp.close_date) }}</span>
            </div>
            <div class="text-caption text-medium-emphasis mt-1">{{ opp.owner?.name ?? 'Unassigned' }}</div>
          </v-card-text>
        </v-card>
        <div v-if="!col.items.length && !loading" class="text-body-2 text-medium-emphasis pa-2">No deals</div>
      </div>
    </div>

    <v-snackbar :model-value="!!snack" color="primary" timeout="3000" @update:model-value="snack = ''">{{ snack }}</v-snackbar>
  </v-container>
</template>

<style scoped>
.board {
  display: grid;
  grid-template-columns: repeat(4, minmax(240px, 1fr));
  gap: 16px;
  overflow-x: auto;
}
.board-column {
  background: rgb(var(--v-theme-background));
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 12px;
  min-height: 200px;
}
.opp-link {
  color: rgb(var(--v-theme-on-surface));
  text-decoration: none;
}
.opp-link:hover {
  text-decoration: underline;
}
</style>
