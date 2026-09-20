<script setup>
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import { ORDINAL_PAIR } from '../../constants'
import { categoryAxis, INK, tooltip } from './chartSetup'

// Committed vs completed story points per sprint (target vs achieved: a light/dark pair).
const props = defineProps({ sprints: { type: Array, required: true } })

const SERIES = [
  { key: 'committed', label: 'Committed', color: ORDINAL_PAIR.light },
  { key: 'completed', label: 'Completed', color: ORDINAL_PAIR.dark },
]

const data = computed(() => ({
  labels: props.sprints.map((s) => (s.in_progress ? `${s.sprint.replace('Sprint ', 'S')}*` : s.sprint.replace('Sprint ', 'S'))),
  datasets: SERIES.map((s) => ({
    label: s.label,
    data: props.sprints.map((row) => row[s.key]),
    backgroundColor: s.color,
    borderRadius: { topLeft: 4, topRight: 4 },
    borderSkipped: 'start',
    maxBarThickness: 16,
    categoryPercentage: 0.7,
    barPercentage: 0.9,
  })),
}))

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: false },
    tooltip: {
      ...tooltip,
      callbacks: {
        title: (items) => {
          const s = props.sprints[items[0].dataIndex]
          return `${s.sprint}${s.in_progress ? ' (in progress)' : ''}${s.goal ? ` · ${s.goal}` : ''}`
        },
        label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw} pts`,
      },
    },
  },
  scales: {
    x: categoryAxis,
    y: { grid: { color: INK.grid }, border: { display: false }, beginAtZero: true, ticks: { maxTicksLimit: 5 } },
  },
}
</script>

<template>
  <div>
    <div class="chart-legend">
      <span v-for="s in SERIES" :key="s.key"><i :style="{ background: s.color }" />{{ s.label }}</span>
      <span class="text-medium-emphasis">* in progress</span>
    </div>
    <div style="height: 240px">
      <Bar :data="data" :options="options" role="img" aria-label="Committed and completed story points per sprint" />
    </div>
  </div>
</template>
