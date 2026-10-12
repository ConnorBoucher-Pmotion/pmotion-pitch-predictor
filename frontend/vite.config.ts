import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages project site default; local `.env` should set VITE_BASE=/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const base = env.VITE_BASE || process.env.VITE_BASE || '/'

  return {
    base,
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 43124,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: process.env.VITE_DEV_API_PROXY || 'http://127.0.0.1:8741',
          changeOrigin: true,
        },
      },
    },
  }
})
