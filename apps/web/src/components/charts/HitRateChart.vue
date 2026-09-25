<script setup>
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { CategoryScale, Chart, LinearScale, LineElement, PointElement } from 'chart.js'
import { ORDINAL_PAIR } from '../../constants'
import { shortSprint } from '../../accuracy'
import { categoryAxis, INK, tooltip } from './chartSetup'

Chart.register(LineElement, PointElement, CategoryScale, LinearScale)

// Running share of backtested sprints that finished by the forecast's P50 and P85 dates, with
// each one's target as a dashed line: a calibrated forecast tracks its target.
const props = defineProps({ sprints: { type: Array, required: true }, targets: { type: Object, required: true } })

const SERIES = [
  { key: 'p85_hit_rate_so_far', target: 'p85_hit_rate', label: 'Met by P85', color: ORDINAL_PAIR.dark },
  { key: 'p50_hit_rate_so_far', target: 'p50_hit_rate', label: 'Met by P50', color: ORDINAL_PAIR.light },
]

const data = computed(() => ({
  labels: props.sprints.map((s) => shortSprint(s.sprint)),
  datasets: SERIES.flatMap((s) => [
    {
      label: s.label,
      data: props.sprints.map((r) => r[s.key] * 100),
      borderColor: s.color,
      backgroundColor: s.color,
      pointRadius: 3,
      tension: 0.2,
    },
    {
      label: `${s.label} target`,
      data: props.sprints.map(() => props.targets[s.target] * 100),
      borderColor: s.color,
      borderDash: [4, 4],
      borderWidth: 1,
      pointRadius: 0,
    },
  ]),
}))

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: false },
    tooltip: { ...tooltip, callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${Math.round(ctx.raw)}%` } },
  },
  scales: {
    x: categoryAxis,
    y: {
      min: 0,
      max: 100,
      grid: { color: INK.grid },
      border: { display: false },
      ticks: { callback: (v) => `${v}%`, maxTicksLimit: 5 },
    },
  },
}
</script>

<template>
  <div>
    <div class="chart-legend">
      <span v-for="s in SERIES" :key="s.key"><i :style="{ background: s.color }" />{{ s.label }} (so far)</span>
      <span class="text-medium-emphasis">dashed: target</span>
    </div>
    <div style="height: 220px">
      <Line :data="data" :options="options" role="img" aria-label="Share of sprints finished by their forecast dates" />
    </div>
  </div>
</template>
