<script setup>
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import { FORECAST_COLORS, stageTitle } from '../../constants'
import { barEndLabels, INK, moneyAxis, tooltip } from './chartSetup'

// One measure across stages: a single series, so no legend (the card title names it).
const props = defineProps({ stages: { type: Array, required: true } })

const data = computed(() => ({
  labels: props.stages.map((s) => `${stageTitle(s.stage)} (${s.count})`),
  datasets: [
    {
      label: 'Open pipeline',
      data: props.stages.map((s) => Number(s.amount)),
      backgroundColor: FORECAST_COLORS.negotiation,
      borderRadius: { topRight: 4, bottomRight: 4 },
      borderSkipped: 'start',
      maxBarThickness: 24,
    },
  ],
}))

const options = {
  indexAxis: 'y',
  responsive: true,
  maintainAspectRatio: false,
  layout: { padding: { right: 56 } },
  plugins: { legend: { display: false }, tooltip },
  scales: {
    x: { ...moneyAxis, beginAtZero: true },
    y: { grid: { display: false }, border: { color: INK.grid }, ticks: { color: INK.primary } },
  },
}
</script>

<template>
  <div style="height: 220px">
    <Bar :data="data" :options="options" :plugins="[barEndLabels]" aria-label="Open pipeline by stage" role="img" />
  </div>
</template>
