<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJson } from '../api'
import ForecastByMonthChart from '../components/charts/ForecastByMonthChart.vue'
import PipelineByStageChart from '../components/charts/PipelineByStageChart.vue'
import PageHeader from '../components/PageHeader.vue'
import { FORECAST_COLORS } from '../constants'
import { money, moneyFull, monthLabel, percent } from '../format'
import { quarterLabel, quarterOf, shiftQuarter } from '../quarters'

const current = quarterOf()
const quarterOptions = [-2, -1, 0, 1].map((by) => {
  const q = shiftQuarter(current, by)
  return { value: quarterLabel(q), title: `${quarterLabel(q)}${by === 0 ? ' (current)' : ''}` }
})
const quarter = ref(quarterLabel(current))
const forecast = ref(null)
const error = ref('')
const loading = ref(false)
const showTable = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    forecast.value = await getJson('/api/v1/forecast', { quarter: quarter.value })
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
watch(quarter, load)
onMounted(load)

const pct = (part) => (forecast.value && Number(forecast.value.quota) ? (Number(part) / Number(forecast.value.quota)) * 100 : 0)

const tiles = computed(() => {
  const f = forecast.value
  if (!f) return []
  return [
    { label: 'Quota', value: money(f.quota), note: 'Sum of rep quotas' },
    { label: 'Closed won', value: money(f.won), note: `${percent(pct(f.won))} of quota` },
    { label: 'Commit', value: money(f.commit), note: `Won + negotiation · ${percent(pct(f.commit))}` },
    { label: 'Best case', value: money(f.best_case), note: `Commit + proposal · ${percent(pct(f.best_case))}` },
    { label: 'Weighted', value: money(f.weighted), note: 'Won + open deals × win probability' },
  ]
})

// Quota meter: segments for won, negotiation and proposal, scaled so quota sits at a fixed mark.
const meter = computed(() => {
  const f = forecast.value
  if (!f) return null
  const scaleMax = Math.max(Number(f.best_case), Number(f.quota)) * 1.05 || 1
  const w = (v) => `${(Math.max(0, v) / scaleMax) * 100}%`
  return {
    segments: [
      { key: 'won', label: 'Closed won', width: w(Number(f.won)), color: FORECAST_COLORS.won },
      { key: 'neg', label: 'Negotiation', width: w(Number(f.commit) - Number(f.won)), color: FORECAST_COLORS.negotiation },
      { key: 'prop', label: 'Proposal', width: w(Number(f.best_case) - Number(f.commit)), color: FORECAST_COLORS.proposal },
    ],
    quotaAt: w(Number(f.quota)),
  }
})

const repHeaders = [
  { title: 'Rep', key: 'rep' },
  { title: 'Quota', key: 'quota', align: 'end' },
  { title: 'Closed won', key: 'won', align: 'end' },
  { title: 'Commit', key: 'commit', align: 'end' },
  { title: 'Weighted', key: 'weighted', align: 'end' },
  { title: 'Attainment', key: 'attainment_pct', align: 'end', width: 220 },
]
const monthHeaders = [
  { title: 'Month', key: 'month' },
  { title: 'Closed won', key: 'won', align: 'end' },
  { title: 'Commit', key: 'commit', align: 'end' },
  { title: 'Best case', key: 'best_case', align: 'end' },
  { title: 'Weighted', key: 'weighted', align: 'end' },
]
</script>

<template>
  <v-container fluid class="pa-6">
    <PageHeader title="Forecast" subtitle="Where the quarter will land, based on deal stage and close date.">
      <v-select v-model="quarter" :items="quarterOptions" density="compact" hide-details style="min-width: 200px" />
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-progress-linear v-if="loading" indeterminate color="secondary" class="mb-2" />

    <template v-if="forecast">
      <v-row>
        <v-col v-for="t in tiles" :key="t.label" cols="12" sm="6" md="">
          <v-card class="pa-4 h-100">
            <div class="text-body-2 text-medium-emphasis">{{ t.label }}</div>
            <div class="kpi-value mt-1">{{ t.value }}</div>
            <div class="text-caption text-medium-emphasis mt-1">{{ t.note }}</div>
          </v-card>
        </v-col>
      </v-row>

      <v-card class="mt-4 pa-4">
        <div class="d-flex justify-space-between text-body-2 mb-2">
          <span class="font-weight-medium">Progress to quota</span>
          <span class="text-medium-emphasis">{{ moneyFull(forecast.won) }} of {{ moneyFull(forecast.quota) }} closed</span>
        </div>
        <div class="meter" role="img" :aria-label="`Closed won is ${percent(pct(forecast.won))} of quota; best case is ${percent(pct(forecast.best_case))}`">
          <div v-for="s in meter.segments" :key="s.key" class="meter-seg" :style="{ width: s.width, background: s.color }" :title="s.label" />
          <div class="quota-mark" :style="{ left: meter.quotaAt }"><span>Quota</span></div>
        </div>
        <div class="legend mt-3">
          <span v-for="s in meter.segments" :key="s.key" class="legend-item"><span class="swatch" :style="{ background: s.color }" />{{ s.label }}</span>
        </div>
      </v-card>

      <v-row class="mt-2">
        <v-col cols="12" lg="7">
          <v-card class="pa-4 h-100">
            <div class="d-flex align-center mb-2">
              <div class="font-weight-medium flex-grow-1">Forecast by month</div>
              <v-btn-toggle v-model="showTable" density="compact" variant="outlined" divided mandatory>
                <v-btn :value="false" size="small">Chart</v-btn>
                <v-btn :value="true" size="small">Table</v-btn>
              </v-btn-toggle>
            </div>
            <ForecastByMonthChart v-if="!showTable" :months="forecast.by_month" />
            <v-data-table v-else :headers="monthHeaders" :items="forecast.by_month" density="compact" hide-default-footer>
              <template #[`item.month`]="{ item }">{{ monthLabel(item.month) }}</template>
              <template v-for="k in ['won', 'commit', 'best_case', 'weighted']" #[`item.${k}`]="{ item }" :key="k">{{ moneyFull(item[k]) }}</template>
            </v-data-table>
          </v-card>
        </v-col>
        <v-col cols="12" lg="5">
          <v-card class="pa-4 h-100">
            <div class="font-weight-medium mb-2">Open pipeline by stage</div>
            <PipelineByStageChart :stages="forecast.by_stage" />
          </v-card>
        </v-col>
      </v-row>

      <v-card class="mt-4" title="By rep">
        <v-data-table :headers="repHeaders" :items="forecast.by_rep" hide-default-footer items-per-page="-1">
          <template #[`item.rep`]="{ item }">{{ item.rep.name }}</template>
          <template v-for="k in ['quota', 'won', 'commit', 'weighted']" #[`item.${k}`]="{ item }" :key="k">{{ moneyFull(item[k]) }}</template>
          <template #[`item.attainment_pct`]="{ item }">
            <div class="d-flex align-center justify-end ga-2">
              <v-progress-linear
                :model-value="Math.min(item.attainment_pct, 100)"
                :color="FORECAST_COLORS.won"
                :bg-color="FORECAST_COLORS.proposal"
                rounded
                height="8"
                style="width: 120px"
              />
              <span style="width: 44px">{{ percent(item.attainment_pct) }}</span>
            </div>
          </template>
        </v-data-table>
      </v-card>
    </template>
  </v-container>
</template>

<style scoped>
.meter {
  position: relative;
  display: flex;
  gap: 2px;
  height: 20px;
  background: #eef1f3;
  border-radius: 4px;
}
.meter-seg:first-child {
  border-radius: 4px 0 0 4px;
}
.meter-seg:last-of-type {
  border-radius: 0 4px 4px 0;
}
.quota-mark {
  position: absolute;
  top: -6px;
  bottom: -6px;
  width: 2px;
  background: #1f2733;
}
.quota-mark span {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: #1f2733;
  white-space: nowrap;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #5b6573;
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
