import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base: './' -> assets load relative to index.html, so the Python server can
// serve the build from any path. Dev proxy forwards /api to serve.py.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
