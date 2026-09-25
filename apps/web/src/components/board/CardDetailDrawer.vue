<script setup>
import { computed } from 'vue'
import { BOARD_COLUMNS, MODULE_LABELS, TIER_COLORS } from '../../constants'

const props = defineProps({ card: { type: Object, default: null } })
defineEmits(['close'])

const columnTitle = computed(() => {
  if (!props.card) return ''
  return BOARD_COLUMNS.find((c) => c.key === props.card.column)?.title ?? props.card.column
})

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
</script>

<template>
  <v-navigation-drawer
    :model-value="!!card"
    location="right"
    temporary
    width="380"
    @update:model-value="(v) => !v && $emit('close')"
  >
    <template v-if="card">
      <div class="pa-4">
        <div class="d-flex align-center justify-space-between mb-1">
          <v-chip size="small" variant="tonal">{{ columnTitle }}</v-chip>
          <v-btn icon="mdi-close" variant="text" size="small" @click="$emit('close')" />
        </div>
        <h2 class="drawer-title">{{ card.title }}</h2>
        <div class="text-caption text-medium-emphasis mb-4">
          <span v-if="card.issue_number">Issue #{{ card.issue_number }}</span>
          <span v-if="card.issue_number && card.pr_number"> · </span>
          <span v-if="card.pr_number">PR #{{ card.pr_number }}</span>
          <span> · {{ card.source === 'synthetic' ? 'Simulated' : 'GitHub' }}</span>
        </div>

        <v-table density="compact" class="mb-4">
          <tbody>
            <tr>
              <td class="text-medium-emphasis">Module</td>
              <td>{{ MODULE_LABELS[card.module] ?? card.module ?? '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">Points</td>
              <td>{{ card.points ?? '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">Owner</td>
              <td>{{ card.owner ?? '—' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">Sprint</td>
              <td>{{ card.sprint ?? '—' }}</td>
            </tr>
            <tr v-if="card.tier">
              <td class="text-medium-emphasis">Risk tier</td>
              <td>
                <v-chip size="x-small" :color="TIER_COLORS[card.tier] ?? 'default'" variant="flat">
                  {{ card.tier }}
                </v-chip>
                <span v-if="card.risk_score != null" class="ml-2">score {{ card.risk_score }}</span>
              </td>
            </tr>
            <tr v-if="card.gate_missing.length">
              <td class="text-medium-emphasis">Gate missing</td>
              <td>{{ card.gate_missing.join(', ') }}</td>
            </tr>
            <tr v-if="card.release && card.column === 'merged'">
              <td class="text-medium-emphasis">Release gate</td>
              <td>
                {{ card.release.description || card.release.reasons.join('; ') }}
                <span v-if="card.source === 'synthetic'" class="text-medium-emphasis">
                  (simulated)
                </span>
              </td>
            </tr>
            <tr v-if="card.rolled_back">
              <td class="text-medium-emphasis">Rollback</td>
              <td class="text-error">This deployment was rolled back</td>
            </tr>
          </tbody>
        </v-table>

        <div class="section-title mb-2">Timeline</div>
        <v-timeline density="compact" side="end" class="mb-4">
          <v-timeline-item
            v-for="([name, at], i) in card.transitions"
            :key="i"
            size="x-small"
            dot-color="secondary"
          >
            <div class="text-caption">
              <strong>{{ BOARD_COLUMNS.find((c) => c.key === name)?.title ?? name }}</strong>
              — {{ fmt(at) }}
            </div>
          </v-timeline-item>
        </v-timeline>

        <template v-if="card.decisions.length">
          <div class="section-title mb-2">Agent decisions</div>
          <v-card
            v-for="d in card.decisions"
            :key="d.id"
            variant="outlined"
            density="compact"
            class="pa-3 mb-2"
          >
            <div class="d-flex align-center justify-space-between mb-1">
              <span class="text-caption font-weight-medium">{{ d.agent }}</span>
              <span class="text-caption text-medium-emphasis">{{ fmt(d.created_at) }}</span>
            </div>
            <div v-if="d.tier" class="mb-1">
              <v-chip size="x-small" :color="TIER_COLORS[d.tier] ?? 'default'" variant="flat">
                {{ d.tier }}
              </v-chip>
              <span v-if="d.final_score != null" class="text-caption ml-2">
                score {{ d.final_score }}
              </span>
            </div>
            <div v-if="d.signals" class="signal-grid">
              <div v-for="(v, k) in d.signals" :key="k" class="text-caption">
                <span class="text-medium-emphasis">{{ k.replaceAll('_', ' ') }}:</span> {{ v }}
              </div>
            </div>
            <div v-if="d.human_override" class="text-caption mt-1 text-warning">
              Overridden by a human label correction
            </div>
          </v-card>
        </template>
      </div>
    </template>
  </v-navigation-drawer>
</template>

<style scoped>
.drawer-title {
  font-size: 17px;
  font-weight: 700;
  line-height: 1.3;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
}
.signal-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px 12px;
}
</style>
