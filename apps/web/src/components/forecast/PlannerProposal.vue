<script setup>
// The planner agent's latest draft for a slipping sprint. It only ever proposes: nothing here
// changes the sprint. Every effect shown was measured by re-running the forecast, not by the model.
import { computed } from 'vue'
import { ACTION_LABELS, effectLabel } from '../../forecast'

const props = defineProps({
  proposal: { type: Object, default: null },
  slipping: { type: Boolean, default: false },
})

const drafted = computed(() =>
  props.proposal
    ? new Date(props.proposal.created_at).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
    : '',
)
</script>

<template>
  <div v-if="proposal || slipping" class="proposal">
    <div class="d-flex align-center flex-wrap ga-2 mb-2">
      <v-icon icon="mdi-lightbulb-on-outline" size="18" color="accent" />
      <span class="figure-label">Planner's draft</span>
      <span class="text-caption text-medium-emphasis">
        Proposes only: nothing has been changed. You decide.
      </span>
      <v-spacer />
      <v-chip
        v-if="proposal && proposal.status === 'ok' && !proposal.current"
        size="x-small"
        variant="tonal"
        color="warning"
        title="The forecast has changed since this was drafted; a new draft follows on the next poll."
      >
        Drafted for an earlier forecast
      </v-chip>
    </div>

    <p v-if="!proposal" class="text-body-2 text-medium-emphasis">
      The sprint is slipping. The planner drafts options on the agent loop's next poll.
    </p>

    <v-alert
      v-else-if="proposal.status !== 'ok'"
      type="warning"
      variant="tonal"
      density="compact"
      class="text-body-2"
    >
      The planner's last attempt ({{ drafted }}) failed: {{ proposal.status }}. It retries up to
      three times, five minutes apart. Decision #{{ proposal.decision_id }} in the Decision log has
      the full error.
    </v-alert>

    <template v-else>
      <p class="text-body-2 mb-3">{{ proposal.summary }}</p>
      <div
        v-for="(option, i) in proposal.options"
        :key="i"
        class="option"
        :class="{ 'option--recommended': i === proposal.recommended }"
      >
        <div class="d-flex align-center flex-wrap ga-2">
          <v-chip size="x-small" variant="flat" color="primary">
            {{ ACTION_LABELS[option.action] ?? option.action }}
          </v-chip>
          <span class="text-body-2 font-weight-medium">{{ option.title }}</span>
          <v-chip
            v-if="i === proposal.recommended"
            size="x-small"
            variant="tonal"
            color="secondary"
          >
            Recommended
          </v-chip>
        </div>
        <div class="d-flex align-center flex-wrap ga-1 mt-1">
          <v-chip
            v-for="n in option.items"
            :key="n"
            size="x-small"
            variant="outlined"
            density="compact"
          >
            #{{ n }}
          </v-chip>
          <span v-if="option.reassign_to" class="text-caption text-medium-emphasis">
            → {{ option.reassign_to }}
          </span>
        </div>
        <div class="text-body-2 text-medium-emphasis mt-1">{{ option.rationale }}</div>
        <div v-if="effectLabel(option.effect)" class="effect mt-1">
          <v-icon icon="mdi-chart-bell-curve-cumulative" size="14" />
          {{ effectLabel(option.effect) }}
          <span class="text-medium-emphasis">(measured by re-running the forecast)</span>
        </div>
        <div v-else class="text-caption text-medium-emphasis mt-1">
          The forecast counts items, not who does them or how they're cut, so this one isn't
          measured.
        </div>
      </div>
      <div class="text-caption text-medium-emphasis mt-2">
        Drafted {{ drafted }} by {{ proposal.model }} · confidence
        {{ Math.round(proposal.confidence * 100) }}% ·
        {{ proposal.input_tokens?.toLocaleString() }} in /
        {{ proposal.output_tokens?.toLocaleString() }} out tokens · decision
        #{{ proposal.decision_id }} in the Decision log
        <template v-if="proposal.dropped?.length">
          · code removed {{ proposal.dropped.length }} thing{{ proposal.dropped.length === 1 ? '' : 's' }}
          the model named that weren't real ({{ proposal.dropped.join('; ') }})
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.proposal {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.figure-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.option {
  padding: 10px 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 6px;
  margin-bottom: 8px;
}
.option--recommended {
  border-color: rgb(var(--v-theme-secondary));
}
.effect {
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: rgb(var(--v-theme-secondary));
}
</style>
