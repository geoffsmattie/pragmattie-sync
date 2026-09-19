<script setup>
import BrandFooter from './components/BrandFooter.vue'

const nav = [
  { title: 'Home', icon: 'mdi-home-outline', to: '/' },
  { title: 'Leads', icon: 'mdi-account-plus-outline', to: '/leads' },
  { title: 'Accounts', icon: 'mdi-domain', to: '/accounts' },
  { title: 'Pipeline', icon: 'mdi-view-column-outline', to: '/pipeline' },
  { title: 'Forecast', icon: 'mdi-chart-line', to: '/forecast' },
  { title: 'Orchestration', icon: 'mdi-robot-outline', phase: 4 },
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
        <v-list-item
          v-for="item in nav"
          :key="item.title"
          :to="item.to"
          :exact="item.to === '/'"
          :prepend-icon="item.icon"
          :title="item.title"
          :subtitle="item.phase ? `Coming in Phase ${item.phase}` : undefined"
          :disabled="!item.to"
        />
      </v-list>
    </v-navigation-drawer>

    <v-main>
      <router-view />
    </v-main>

    <BrandFooter app />
  </v-app>
</template>


<style>
.kpi-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
</style>
