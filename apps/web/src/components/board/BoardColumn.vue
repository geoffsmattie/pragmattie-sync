<script setup>
import BoardCard from './BoardCard.vue'

defineProps({
  title: { type: String, required: true },
  cards: { type: Array, required: true },
  wip: { type: Number, default: 0 },
  medianAgeHours: { type: Number, default: null },
  movedKeys: { type: Set, required: true },
})
defineEmits(['open-card'])

function formatAge(hours) {
  if (hours == null) return '—'
  if (hours < 48) return `${Math.round(hours)}h`
  return `${Math.round(hours / 24)}d`
}
</script>

<template>
  <v-card class="board-column" variant="flat">
    <div class="column-header pa-2">
      <div class="d-flex align-center justify-space-between">
        <span class="column-title">{{ title }}</span>
        <v-chip size="x-small" density="compact" variant="tonal">{{ wip }}</v-chip>
      </div>
      <div class="text-caption text-medium-emphasis" title="Median time in this column">
        median age {{ formatAge(medianAgeHours) }}
      </div>
    </div>
    <div class="column-body pa-2">
      <TransitionGroup name="board-card-list">
        <BoardCard
          v-for="card in cards"
          :key="card.key"
          :card="card"
          :moved="movedKeys.has(card.key)"
          @open="$emit('open-card', $event)"
        />
      </TransitionGroup>
      <div v-if="!cards.length" class="text-caption text-medium-emphasis empty-note">Empty</div>
    </div>
  </v-card>
</template>

<style scoped>
.board-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 0;
  background: #f6f8f9;
  height: 100%;
}
.column-header {
  border-bottom: 1px solid #e3e8ea;
}
.column-title {
  font-size: 13px;
  font-weight: 600;
}
.column-body {
  overflow-y: auto;
  flex: 1 1 auto;
  min-height: 80px;
}
.empty-note {
  text-align: center;
  padding: 12px 0;
}
.board-card-list-move,
.board-card-list-enter-active,
.board-card-list-leave-active {
  transition: all 0.4s ease;
}
.board-card-list-enter-from,
.board-card-list-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
.board-card-list-leave-active {
  position: absolute;
}
</style>
