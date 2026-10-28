import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api/* -> server FastAPI (giống nginx khi chạy bằng Docker)
const target = process.env.CSM_API_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
