import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

export const routes = [
  { path: '/', name: 'home', component: HomeView },
  { path: '/leads', name: 'leads', component: () => import('../views/LeadsView.vue') },
  { path: '/accounts', name: 'accounts', component: () => import('../views/AccountsView.vue') },
  {
    path: '/accounts/:id',
    name: 'account',
    component: () => import('../views/AccountDetailView.vue'),
    props: true,
  },
  { path: '/pipeline', name: 'pipeline', component: () => import('../views/PipelineView.vue') },
  { path: '/forecast', name: 'forecast', component: () => import('../views/ForecastView.vue') },
  {
    path: '/engineering',
    name: 'engineering',
    component: () => import('../views/EngineeringView.vue'),
  },
  {
    path: '/board',
    name: 'board',
    component: () => import('../views/BoardView.vue'),
  },
  {
    path: '/delivery',
    name: 'delivery',
    component: () => import('../views/DeliveryForecastView.vue'),
  },
  {
    path: '/accuracy',
    name: 'accuracy',
    component: () => import('../views/AccuracyView.vue'),
  },
  {
    path: '/decisions',
    name: 'decisions',
    component: () => import('../views/DecisionLogView.vue'),
  },
]

export default createRouter({ history: createWebHistory(), routes })
