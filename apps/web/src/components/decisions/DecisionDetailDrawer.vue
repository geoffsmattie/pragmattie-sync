<script setup>
import { computed } from 'vue'
import { TIER_COLORS } from '../../constants'
import { statusColor, subjectLabel } from '../../decisions'

const props = defineProps({ decision: { type: Object, default: null } })
defineEmits(['close'])

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })
}

const label = computed(() => (props.decision ? subjectLabel(props.decision) : ''))
</script>

<template>
  <v-navigation-drawer
    :model-value="!!decision"
    location="right"
    temporary
    width="420"
    @update:model-value="(v) => !v && $emit('close')"
  >
    <template v-if="decision">
      <div class="pa-4">
        <div class="d-flex align-center justify-space-between mb-1">
          <v-chip size="small" :color="statusColor(decision.status)" variant="tonal">
            {{ decision.status }}
          </v-chip>
          <v-btn icon="mdi-close" variant="text" size="small" @click="$emit('close')" />
        </div>
        <h2 class="drawer-title">{{ decision.agent }} · {{ label }}</h2>
        <div class="text-caption text-medium-emphasis mb-4">
          {{ fmt(decision.created_at) }} · {{ decision.trigger }} · attempt {{ decision.attempt }}
        </div>

        <v-table density="compact" class="mb-4">
          <tbody>
            <tr>
              <td class="text-medium-emphasis">Source</td>
              <td>{{ decision.subject_source === 'synthetic' ? 'Simulated' : 'GitHub' }}</td>
            </tr>
            <tr>
              <td class="text-medium-emphasis">Model</td>
              <td>{{ decision.model_id ?? '—' }}</td>
            </tr>
            <tr v-if="decision.prompt_version">
              <td class="text-medium-emphasis">Prompt</td>
              <td>{{ decision.prompt_version }} · {{ decision.prompt_hash?.slice(0, 12) ?? '—' }}</td>
            </tr>
            <tr v-if="decision.head_sha">
              <td class="text-medium-emphasis">Version scored</td>
              <td class="mono">{{ decision.head_sha }}</td>
            </tr>
            <tr v-if="decision.tier">
              <td class="text-medium-emphasis">Tier</td>
              <td>
                <v-chip size="x-small" :color="TIER_COLORS[decision.tier] ?? 'default'" variant="flat">
                  {{ decision.tier }}
                </v-chip>
                <span v-if="decision.final_score != null" class="ml-2">
                  score {{ decision.final_score }}
                  <span v-if="decision.raw_score != null" class="text-caption text-medium-emphasis">
                    (raw {{ decision.raw_score }}<template v-if="decision.adjustment != null">, adj {{ decision.adjustment > 0 ? '+' : '' }}{{ decision.adjustment }}</template>)
                  </span>
                </span>
              </td>
            </tr>
            <tr v-if="decision.latency_ms != null">
              <td class="text-medium-emphasis">Latency</td>
              <td>{{ decision.latency_ms }}ms</td>
            </tr>
            <tr v-if="decision.input_tokens != null || decision.output_tokens != null">
              <td class="text-medium-emphasis">Tokens</td>
              <td>{{ decision.input_tokens ?? 0 }} in / {{ decision.output_tokens ?? 0 }} out</td>
            </tr>
            <tr v-if="decision.supersedes_id">
              <td class="text-medium-emphasis">Supersedes</td>
              <td>decision #{{ decision.supersedes_id }}</td>
            </tr>
          </tbody>
        </v-table>

        <template v-if="decision.error">
          <div class="section-title mb-2">Error</div>
          <v-card variant="outlined" density="compact" class="pa-3 mb-4 text-error text-caption">
            {{ decision.error }}
          </v-card>
        </template>

        <template v-if="decision.signals">
          <div class="section-title mb-2">Signals</div>
          <div class="signal-grid mb-4">
            <div v-for="(v, k) in decision.signals" :key="k" class="text-caption">
              <span class="text-medium-emphasis">{{ k.replaceAll('_', ' ') }}:</span> {{ v }}
            </div>
          </div>
        </template>

        <template v-if="decision.human_override">
          <div class="section-title mb-2">Human override</div>
          <v-card variant="outlined" density="compact" class="pa-3 mb-4 text-caption">
            <pre class="mono">{{ JSON.stringify(decision.human_override, null, 2) }}</pre>
          </v-card>
        </template>

        <template v-if="decision.output">
          <div class="section-title mb-2">Agent output</div>
          <v-card variant="outlined" density="compact" class="pa-3 mb-4">
            <pre class="mono output-json">{{ JSON.stringify(decision.output, null, 2) }}</pre>
          </v-card>
        </template>

        <template v-if="decision.action_taken">
          <div class="section-title mb-2">Action taken</div>
          <v-card variant="outlined" density="compact" class="pa-3">
            <pre class="mono output-json">{{ JSON.stringify(decision.action_taken, null, 2) }}</pre>
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
.mono {
  font-family: ui-monospace, 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
}
.output-json {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}
</style>
