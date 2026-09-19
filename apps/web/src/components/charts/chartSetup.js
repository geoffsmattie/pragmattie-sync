import {
  BarElement,
  CategoryScale,
  Chart,
  LinearScale,
  Tooltip,
} from 'chart.js'
import { money, moneyFull } from '../../format'

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip)

export const INK = {
  primary: '#1F2733',
  secondary: '#5B6573',
  grid: '#E6E8EB',
  surface: '#FFFFFF',
}

Chart.defaults.font.family = 'Roboto, system-ui, sans-serif'
Chart.defaults.color = INK.secondary

export const moneyAxis = {
  grid: { color: INK.grid, lineWidth: 1 },
  border: { display: false },
  ticks: { callback: (v) => money(v), maxTicksLimit: 6 },
}

export const categoryAxis = {
  grid: { display: false },
  border: { color: INK.grid },
  ticks: { color: INK.secondary },
}

export const tooltip = {
  backgroundColor: INK.primary,
  padding: 10,
  cornerRadius: 6,
  boxPadding: 4,
  callbacks: {
    label: (ctx) => ` ${ctx.dataset.label}: ${moneyFull(ctx.raw)}`,
  },
}

/** Draws the value just past the end of each bar (horizontal bar charts). */
export const barEndLabels = {
  id: 'barEndLabels',
  afterDatasetsDraw(chart) {
    const { ctx } = chart
    ctx.save()
    ctx.font = '500 12px Roboto, system-ui, sans-serif'
    ctx.fillStyle = INK.primary
    ctx.textBaseline = 'middle'
    chart.getDatasetMeta(0).data.forEach((bar, i) => {
      const value = chart.data.datasets[0].data[i]
      if (value) ctx.fillText(money(value), bar.x + 6, bar.y)
    })
    ctx.restore()
  },
}
