import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api to the local Flask backend, so the frontend never
// needs a hard-coded host and everything stays on localhost (brief §23).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        // Port 5003 by default — 5000 is reserved by macOS AirPlay Receiver.
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5003',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})