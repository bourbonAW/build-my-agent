import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  build: {
    chunkSizeWarningLimit: 700,
  },
  plugins: [react()],
  server: {
    proxy: {
      // Forward the UI's relative /api/* calls to the read API (api.serve).
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.tsx'],
    setupFiles: './src/setupTests.ts',
  },
})
