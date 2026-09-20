<script setup>
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { CategoryScale, Chart, LinearScale, LineElement, PointElement } from 'chart.js'
import { ORDINAL_PAIR } from '../../constants'
import { categoryAxis, INK, tooltip } from './chartSetup'

Chart.register(LineElement, PointElement, CategoryScale, LinearScale)

// PR cycle time (opened -> merged) per sprint: the typical PR and the slow tail.
const props = defineProps({ sprints: { type: Array, required: true } })

const SERIES = [
  { key: 'median_hours', label: 'Median', color: ORDINAL_PAIR.dark },
  { key: 'p85_hours', label: '85th percentile', color: ORDINAL_PAIR.light },
]

const short = (s) => `${s.sprint.replace('Sprint ', 'S')}${s.in_progress ? '*' : ''}`

const data = computed(() => ({
  labels: props.sprints.map(short),
  datasets: SERIES.map((s) => ({
    label: s.label,
    data: props.sprints.map((row) => row[s.key]),
    borderColor: s.color,
    backgroundColor: s.color,
    borderWidth: 2,
    pointRadius: 4,
    pointBorderColor: INK.surface,
    pointBorderWidth: 2,
    pointHoverRadius: 5,
    pointHoverBorderColor: INK.surface,
    pointHoverBorderWidth: 2,
    tension: 0.25,
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
          return `${s.sprint}${s.in_progress ? ' (in progress)' : ''} · ${s.merged} PRs merged`
        },
        label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw} h`,
      },
    },
  },
  scales: {
    x: categoryAxis,
    y: {
      grid: { color: INK.grid },
      border: { display: false },
      beginAtZero: true,
      ticks: { callback: (v) => `${v} h`, maxTicksLimit: 5 },
    },
  },
}
</script>

<template>
  <div>
    <div class="chart-legend">
      <span v-for="s in SERIES" :key="s.key"><i :style="{ background: s.color }" />{{ s.label }}</span>
    </div>
    <div style="height: 240px">
      <Line :data="data" :options="options" role="img" aria-label="Pull request cycle time in hours, by sprint" />
    </div>
  </div>
</template>
