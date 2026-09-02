import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard talks to the FastAPI backend. In dev we proxy /api -> :8000
// so there are no CORS surprises; in production set VITE_API_BASE_URL to the
// deployed backend URL (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
