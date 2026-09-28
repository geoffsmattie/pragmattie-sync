import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  // pragmattie-sync.localhost reaches Vite through the proxy service (proxy/Caddyfile).
  server: { port: 5173, allowedHosts: ['pragmattie-sync.localhost'] },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.spec.js'],
  },
})
