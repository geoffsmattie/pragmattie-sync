<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { getOrchJson } from '../api'
import { cardAtTime, columnStatsAt, deriveFilterOptions, groupByColumn, movedCardKeys } from '../board'
import BoardColumn from '../components/board/BoardColumn.vue'
import CardDetailDrawer from '../components/board/CardDetailDrawer.vue'
import PageHeader from '../components/PageHeader.vue'
import { BOARD_COLUMNS, MODULE_LABELS } from '../constants'

const POLL_MS = 15_000
const REPLAY_OPTIONS = [7, 14, 30, 60]
const REPLAY_FRAMES = 120
const REPLAY_DURATION_MS = 12_000

const board = ref(null)
const loading = ref(true)
const error = ref('')
const movedKeys = ref(new Set())
const selectedCard = ref(null)

const filters = reactive({ sprint: 'current', module: '', owner: '', source: '' })
const filterOptions = ref({ sprints: [], modules: [], owners: [] })

const replayDays = ref(30)
const replaying = ref(false)
const replayAsOf = ref(null)
const replayStart = ref(null)
const replayEnd = ref(null)
let pollTimer = null
let replayTimer = null

async function loadBoard() {
  try {
    const data = await getOrchJson('/api/v1/signals/board', {
      sprint: filters.sprint,
      module: filters.module,
      owner: filters.owner,
      source: filters.source,
    })
    const moved = movedCardKeys(board.value?.cards ?? [], data.cards)
    board.value = data
    if (moved.size) {
      movedKeys.value = moved
      setTimeout(() => {
        movedKeys.value = new Set()
      }, 1800)
    }
    error.value = ''
  } catch (err) {
    error.value = `${err.message}. Is the orchestrator service running on port 8001?`
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions() {
  try {
    const all = await getOrchJson('/api/v1/signals/board', { sprint: 'all' })
    filterOptions.value = deriveFilterOptions(all.cards)
  } catch {
    // Dropdowns just stay sparse; the main board load surfaces the real connectivity error.
  }
}

function onFilterChange() {
  stopReplay()
  loadBoard()
}

const displayCards = computed(() => {
  if (!board.value) return []
  if (replaying.value && replayAsOf.value) {
    return board.value.cards.map((c) => cardAtTime(c, replayAsOf.value)).filter(Boolean)
  }
  return board.value.cards
})

const cardsByColumn = computed(() => groupByColumn(displayCards.value, BOARD_COLUMNS))

const columnStats = computed(() => {
  if (!board.value) return {}
  if (!replaying.value) return board.value.columns
  const now = replayAsOf.value ?? new Date(board.value.generated_at)
  return columnStatsAt(displayCards.value, now, BOARD_COLUMNS)
})

const replayLabel = computed(() => {
  if (!replaying.value || !replayAsOf.value) return ''
  return replayAsOf.value.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
})

const replayProgress = computed(() => {
  if (!replaying.value || !replayAsOf.value || !replayStart.value || !replayEnd.value) return 0
  const span = replayEnd.value.getTime() - replayStart.value.getTime()
  if (span <= 0) return 100
  return ((replayAsOf.value.getTime() - replayStart.value.getTime()) / span) * 100
})

function startReplay() {
  if (!board.value) return
  stopReplayTimerOnly()
  replaying.value = true
  const end = new Date(board.value.generated_at)
  const start = new Date(end.getTime() - replayDays.value * 86_400_000)
  replayStart.value = start
  replayEnd.value = end
  replayAsOf.value = start
  let frame = 0
  replayTimer = setInterval(() => {
    frame += 1
    const frac = Math.min(1, frame / REPLAY_FRAMES)
    replayAsOf.value = new Date(start.getTime() + frac * (end.getTime() - start.getTime()))
    if (frac >= 1) stopReplay()
  }, REPLAY_DURATION_MS / REPLAY_FRAMES)
}

function stopReplayTimerOnly() {
  if (replayTimer) clearInterval(replayTimer)
  replayTimer = null
}

function stopReplay() {
  stopReplayTimerOnly()
  replaying.value = false
  replayAsOf.value = null
  replayStart.value = null
  replayEnd.value = null
  loadBoard()
}

function openCard(card) {
  if (replaying.value) stopReplay()
  selectedCard.value = card
}

onMounted(async () => {
  await Promise.all([loadFilterOptions(), loadBoard()])
  pollTimer = setInterval(() => {
    if (!replaying.value) loadBoard()
  }, POLL_MS)
})

onBeforeUnmount(() => {
  clearInterval(pollTimer)
  stopReplayTimerOnly()
})
</script>

<template>
  <v-container fluid class="pa-6 board-view">
    <PageHeader title="Delivery board" subtitle="Live-derived from the tracked issues, PRs and deployments — nothing here is a stored status.">
      <div class="d-flex align-center flex-wrap ga-2">
        <v-select
          v-model="filters.sprint"
          :items="[
            { title: 'Current sprint', value: 'current' },
            { title: 'All sprints', value: 'all' },
            ...filterOptions.sprints.map((s) => ({ title: s, value: s })),
          ]"
          label="Sprint"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.module"
          :items="[
            { title: 'All modules', value: '' },
            ...filterOptions.modules.map((m) => ({ title: MODULE_LABELS[m] ?? m, value: m })),
          ]"
          label="Module"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.owner"
          :items="[{ title: 'All owners', value: '' }, ...filterOptions.owners]"
          label="Owner"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
          @update:model-value="onFilterChange"
        />
        <v-select
          v-model="filters.source"
          :items="[
            { title: 'All sources', value: '' },
            { title: 'Simulated', value: 'synthetic' },
            { title: 'Real (GitHub)', value: 'github' },
          ]"
          label="Source"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
          @update:model-value="onFilterChange"
        />
      </div>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="secondary" class="mb-4" />

    <div class="d-flex align-center ga-3 mb-4 replay-bar">
      <template v-if="!replaying">
        <v-select
          v-model="replayDays"
          :items="REPLAY_OPTIONS.map((d) => ({ title: `Last ${d} days`, value: d }))"
          density="compact"
          variant="outlined"
          hide-details
          style="width: 150px"
        />
        <v-btn
          prepend-icon="mdi-play-circle-outline"
          variant="tonal"
          size="small"
          :disabled="!board"
          @click="startReplay"
        >
          Replay
        </v-btn>
      </template>
      <template v-else>
        <v-chip color="secondary" variant="flat" prepend-icon="mdi-play-circle-outline">
          Replay · {{ replayLabel }}
        </v-chip>
        <v-progress-linear
          :model-value="replayProgress"
          color="secondary"
          height="6"
          rounded
          style="width: 200px"
        />
        <v-btn prepend-icon="mdi-stop-circle-outline" variant="text" size="small" @click="stopReplay">
          Stop
        </v-btn>
      </template>
    </div>

    <div v-if="board" class="board-columns">
      <BoardColumn
        v-for="col in BOARD_COLUMNS"
        :key="col.key"
        :title="columnStats[col.key]?.title ?? col.title"
        :cards="cardsByColumn[col.key]"
        :wip="columnStats[col.key]?.wip ?? 0"
        :median-age-hours="columnStats[col.key]?.median_age_hours ?? null"
        :moved-keys="movedKeys"
        @open-card="openCard"
      />
    </div>

    <CardDetailDrawer :card="selectedCard" @close="selectedCard = null" />
  </v-container>
</template>

<style scoped>
.board-view {
  max-width: 100%;
}
.board-columns {
  display: flex;
  gap: 10px;
  align-items: stretch;
  height: calc(100vh - 280px);
  min-height: 420px;
}
.replay-bar {
  min-height: 40px;
}
</style>
