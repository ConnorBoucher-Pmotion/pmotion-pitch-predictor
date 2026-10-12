import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages project site: /pmotion-pitch-predictor/
// Override with VITE_BASE=/ for root hosting.
const base = process.env.VITE_BASE || '/pmotion-pitch-predictor/'

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY || 'http://127.0.0.1:8741',
        changeOrigin: true,
      },
    },
  },
})
