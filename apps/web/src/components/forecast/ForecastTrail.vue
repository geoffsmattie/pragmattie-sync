<script setup>
// A small chart of how a forecast's P50 (line) and P85 (upper edge of the band) have moved
// across its saved forecasts, oldest on the left. Higher means later.
import { computed } from 'vue'
import { trailPoints } from '../../forecast'

const props = defineProps({ trail: { type: Array, default: () => [] } })

const W = 220
const H = 44
const PAD = 4

const shape = computed(() => {
  const t = trailPoints(props.trail)
  if (!t) return null
  const x = (i) => PAD + (i / Math.max(1, t.count - 1)) * (W - 2 * PAD)
  const y = (days) => H - PAD - (days / t.span) * (H - 2 * PAD)
  const line = (pts) => pts.map(([i, d]) => `${x(i).toFixed(1)},${y(d).toFixed(1)}`).join(' ')
  const band = `${line(t.p50)} ${line([...t.p85].reverse())}`
  const [li, ld] = t.p50[t.p50.length - 1]
  return { band, p50: line(t.p50), end: { x: x(li), y: y(ld) }, count: t.count }
})
</script>

<template>
  <div class="trail">
    <svg
      v-if="shape"
      :viewBox="`0 0 ${W} ${H}`"
      :width="W"
      :height="H"
      role="img"
      :aria-label="`How the forecast moved across its last ${shape.count} saved forecasts`"
    >
      <polygon :points="shape.band" class="band" />
      <polyline :points="shape.p50" class="p50" />
      <circle :cx="shape.end.x" :cy="shape.end.y" r="3" class="end" />
    </svg>
    <span v-else class="text-caption text-medium-emphasis">
      The trail appears once the date has been forecast more than once.
    </span>
  </div>
</template>

<style scoped>
.trail {
  min-height: 44px;
  display: flex;
  align-items: center;
}
svg {
  max-width: 100%;
  height: auto;
  overflow: visible;
}
.band {
  fill: rgb(var(--v-theme-secondary));
  fill-opacity: 0.15;
  stroke: none;
}
.p50 {
  fill: none;
  stroke: rgb(var(--v-theme-secondary));
  stroke-width: 2;
  stroke-linejoin: round;
}
.end {
  fill: rgb(var(--v-theme-secondary));
}
</style>
