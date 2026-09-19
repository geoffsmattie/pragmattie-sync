<script setup>
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import { FORECAST_COLORS } from '../../constants'
import { monthLabel } from '../../format'
import { categoryAxis, INK, moneyAxis, tooltip } from './chartSetup'

// Stacked columns: closed won + negotiation + proposal = best case for each month.
const props = defineProps({ months: { type: Array, required: true } })

const SERIES = [
  { key: 'won', label: 'Closed won', color: FORECAST_COLORS.won },
  { key: 'negotiation', label: 'Negotiation (commit)', color: FORECAST_COLORS.negotiation },
  { key: 'proposal', label: 'Proposal (best case)', color: FORECAST_COLORS.proposal },
]

const rows = computed(() =>
  props.months.map((m) => ({
    month: monthLabel(m.month),
    won: Number(m.won),
    negotiation: Number(m.commit) - Number(m.won),
    proposal: Number(m.best_case) - Number(m.commit),
  })),
)

const data = computed(() => ({
  labels: rows.value.map((r) => r.month),
  datasets: SERIES.map((s, i) => ({
    label: s.label,
    data: rows.value.map((r) => r[s.key]),
    backgroundColor: s.color,
    // 2px surface gap between stacked segments; only the top segment gets rounded ends.
    borderColor: INK.surface,
    borderWidth: { top: i === 0 ? 0 : 2 },
    borderSkipped: false,
    borderRadius: i === SERIES.length - 1 ? { topLeft: 4, topRight: 4 } : 0,
    maxBarThickness: 24,
  })),
}))

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: { legend: { display: false }, tooltip },
  scales: {
    x: { ...categoryAxis, stacked: true },
    y: { ...moneyAxis, stacked: true, beginAtZero: true },
  },
}

</script>

<template>
  <div>
    <div class="legend" role="list" aria-label="Chart legend">
      <span v-for="s in SERIES" :key="s.key" class="legend-item" role="listitem">
        <span class="swatch" :style="{ background: s.color }" />{{ s.label }}
      </span>
    </div>
    <div style="height: 260px">
      <Bar :data="data" :options="options" aria-label="Forecast by month, stacked by deal stage" role="img" />
    </div>
  </div>
</template>

<style scoped>
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #5b6573;
  margin-bottom: 8px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
</style>
