import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/verify-email': 'http://localhost:8000',
      '/verify-batch': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/analytics': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/pipeline-info': 'http://localhost:8000',
      '/disposable-cache-status': 'http://localhost:8000',
    }
  }
})
