import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import { createVuetify } from 'vuetify'

// Colors are taken from the PragMattie Growth Partners logo.
export const brand = {
  navy: '#2E3F55',
  teal: '#1B8A94',
  gold: '#E8B35A',
  slate: '#8A8D91',
}

export default createVuetify({
  theme: {
    defaultTheme: 'syncvista',
    themes: {
      syncvista: {
        dark: false,
        colors: {
          primary: brand.navy,
          secondary: brand.teal,
          accent: brand.gold,
          background: '#F6F7F9',
          surface: '#FFFFFF',
        },
      },
    },
  },
})
