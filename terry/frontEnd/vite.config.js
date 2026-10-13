import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
