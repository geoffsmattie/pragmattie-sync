import { defineStore } from 'pinia'
import { getJson } from '../api'

// Sales reps change rarely, so they are loaded once and shared across screens.
export const useRepsStore = defineStore('reps', {
  state: () => ({ reps: [], loaded: false }),
  getters: {
    options: (state) => state.reps.map((r) => ({ value: r.id, title: r.name })),
  },
  actions: {
    async load() {
      if (this.loaded) return
      this.reps = await getJson('/api/v1/reps')
      this.loaded = true
    },
  },
})
