import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const API_TARGET = process.env.VITE_API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api':       API_TARGET,
      '/streaming': API_TARGET,
      '/sse':       API_TARGET,
      '/health':    API_TARGET,
      '/webhooks':  API_TARGET,
    },
  },
  build: {
    sourcemap: false,
    minify: 'esbuild',
  },
  esbuild: {
    drop: ['console', 'debugger'],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
