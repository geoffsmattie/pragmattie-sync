<script setup>
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import { categoryAxis, INK, tooltip } from './chartSetup'

// Counts per sprint or week, stacked: e.g. incident PRs the risk score caught vs missed.
const props = defineProps({
  labels: { type: Array, required: true },
  series: { type: Array, required: true }, // [{ label, color, data }]
  ariaLabel: { type: String, required: true },
})

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map((s) => ({
    label: s.label,
    data: s.data,
    backgroundColor: s.color,
    maxBarThickness: 18,
    borderRadius: 2,
  })),
}))

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: false },
    tooltip: { ...tooltip, callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw}` } },
  },
  scales: {
    x: { ...categoryAxis, stacked: true },
    y: {
      stacked: true,
      beginAtZero: true,
      grid: { color: INK.grid },
      border: { display: false },
      ticks: { precision: 0, maxTicksLimit: 5 },
    },
  },
}
</script>

<template>
  <div>
    <div class="chart-legend">
      <span v-for="s in series" :key="s.label"><i :style="{ background: s.color }" />{{ s.label }}</span>
    </div>
    <div style="height: 200px">
      <Bar :data="data" :options="options" role="img" :aria-label="ariaLabel" />
    </div>
  </div>
</template>
