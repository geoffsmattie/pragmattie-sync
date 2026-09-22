<script setup>
import BrandFooter from './components/BrandFooter.vue'

const nav = [
  { title: 'Home', icon: 'mdi-home-outline', to: '/' },
  { title: 'Leads', icon: 'mdi-account-plus-outline', to: '/leads' },
  { title: 'Accounts', icon: 'mdi-domain', to: '/accounts' },
  { title: 'Pipeline', icon: 'mdi-view-column-outline', to: '/pipeline' },
  { title: 'Forecast', icon: 'mdi-chart-line', to: '/forecast' },
  { header: 'Delivery intelligence' },
  { title: 'Delivery board', icon: 'mdi-kanban', to: '/board' },
  { title: 'Engineering signals', icon: 'mdi-pulse', to: '/engineering' },
  { title: 'Decision log', icon: 'mdi-format-list-checks', to: '/decisions' },
]
</script>

<template>
  <v-app>
    <v-app-bar color="primary" flat>
      <v-app-bar-title>
        <span class="font-weight-bold">PragMattie Sync</span>
        <span class="text-accent ml-1">CRM</span>
      </v-app-bar-title>
    </v-app-bar>

    <v-navigation-drawer permanent width="220">
      <v-list nav density="comfortable">
        <template v-for="item in nav" :key="item.title ?? item.header">
          <v-list-subheader v-if="item.header" class="mt-2">{{ item.header }}</v-list-subheader>
          <v-list-item
            v-else
            :to="item.to"
            :exact="item.to === '/'"
            :prepend-icon="item.icon"
            :title="item.title"
          />
        </template>
      </v-list>
    </v-navigation-drawer>

    <v-main>
      <router-view />
    </v-main>

    <BrandFooter app />
  </v-app>
</template>


<style>
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 13px;
  color: #5b6573;
  margin-bottom: 8px;
}
.chart-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chart-legend i {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.kpi-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
</style>
