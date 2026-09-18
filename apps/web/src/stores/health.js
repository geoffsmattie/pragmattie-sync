import { defineStore } from 'pinia'
import { getJson } from '../api'

// Tracks whether the API and its database are reachable.
export const useHealthStore = defineStore('health', {
  state: () => ({ status: 'unknown', database: 'unknown', error: null, loading: false }),
  getters: {
    isHealthy: (state) => state.status === 'ok' && state.database === 'ok',
  },
  actions: {
    async check() {
      this.loading = true
      this.error = null
      try {
        const body = await getJson('/api/v1/health')
        this.status = body.status
        this.database = body.database
      } catch (err) {
        this.status = 'down'
        this.database = 'unknown'
        this.error = err.message
      } finally {
        this.loading = false
      }
    },
  },
})
