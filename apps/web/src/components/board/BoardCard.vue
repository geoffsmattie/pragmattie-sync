<script setup>
import { computed } from 'vue'
import { releaseChip } from '../../board'
import { MODULE_LABELS, TIER_COLORS } from '../../constants'

const props = defineProps({
  card: { type: Object, required: true },
  moved: { type: Boolean, default: false },
})
defineEmits(['open'])

const idLabel = computed(() => {
  const { issue_number: issue, pr_number: pr } = props.card
  if (issue && pr) return `#${issue} · PR ${pr}`
  if (issue) return `#${issue}`
  return `PR ${pr}`
})

const release = computed(() => releaseChip(props.card))

const ownerInitials = computed(() => {
  const name = props.card.owner
  if (!name) return '?'
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
})

const ageLabel = computed(() => {
  const hours = (Date.now() - new Date(props.card.entered_column_at).getTime()) / 3_600_000
  if (hours < 1) return '<1h'
  if (hours < 48) return `${Math.round(hours)}h`
  return `${Math.round(hours / 24)}d`
})
</script>

<template>
  <v-card
    class="board-card"
    :class="{ 'board-card--moved': moved, 'board-card--rolled-back': card.rolled_back }"
    variant="outlined"
    density="compact"
    @click="$emit('open', card)"
  >
    <div class="d-flex align-center ga-1 mb-1">
      <v-icon
        :icon="card.source === 'synthetic' ? 'mdi-flask-outline' : 'mdi-github'"
        size="12"
        class="text-medium-emphasis"
        :title="card.source === 'synthetic' ? 'Simulated' : 'Real, from GitHub'"
      />
      <span class="text-caption text-medium-emphasis id-label">{{ idLabel }}</span>
      <v-spacer />
      <v-icon
        v-if="card.rolled_back"
        icon="mdi-undo-variant"
        size="14"
        color="error"
        title="Rolled back"
      />
    </div>

    <div class="card-title">{{ card.title }}</div>

    <div class="d-flex align-center flex-wrap ga-1 mt-2">
      <v-chip v-if="card.module" size="x-small" variant="tonal" density="compact">
        {{ MODULE_LABELS[card.module] ?? card.module }}
      </v-chip>
      <v-chip v-if="card.points != null" size="x-small" variant="tonal" density="compact">
        {{ card.points }}pt
      </v-chip>
      <v-chip
        v-if="card.tier"
        size="x-small"
        density="compact"
        :color="TIER_COLORS[card.tier] ?? 'default'"
        variant="flat"
      >
        {{ card.tier }}
      </v-chip>
      <v-chip
        v-if="card.gate_missing.length"
        size="x-small"
        density="compact"
        color="warning"
        variant="tonal"
        :title="card.gate_missing.join(', ')"
      >
        {{ card.gate_missing.length }} missing
      </v-chip>
      <v-chip
        v-if="release"
        size="x-small"
        density="compact"
        :color="release.color"
        variant="tonal"
        :title="release.title"
      >
        {{ release.text }}
      </v-chip>
    </div>

    <div class="d-flex align-center justify-space-between mt-2">
      <v-avatar size="18" color="secondary" class="owner-avatar">
        <span class="text-caption">{{ ownerInitials }}</span>
      </v-avatar>
      <span class="text-caption text-medium-emphasis">{{ ageLabel }}</span>
    </div>
  </v-card>
</template>

<style scoped>
.board-card {
  padding: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  background: rgb(var(--v-theme-surface));
  transition:
    box-shadow 0.3s ease,
    transform 0.3s ease;
}
.board-card:hover {
  border-color: #1b8a94;
}
.board-card--rolled-back {
  border-color: rgb(var(--v-theme-error));
}
.board-card--moved {
  animation: board-card-flash 1.8s ease;
}
@keyframes board-card-flash {
  0% {
    box-shadow: 0 0 0 2px #1b8a94;
    transform: scale(1.02);
  }
  100% {
    box-shadow: none;
    transform: scale(1);
  }
}
.id-label {
  font-size: 11px;
}
.card-title {
  font-size: 13px;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.owner-avatar :deep(span) {
  font-size: 9px;
  color: white;
}
</style>
