import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

export const routes = [
  { path: '/', name: 'home', component: HomeView },
  // Phase 2 adds: /leads, /accounts, /pipeline, /forecast
  // Phase 3+ adds: /orchestration (the predictive SDLC dashboard)
]

export default createRouter({ history: createWebHistory(), routes })
