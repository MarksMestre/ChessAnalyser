import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `base` puts every asset URL under the served prefix, so the app works at any
// nesting depth -- /report.html/ and /report.html/games/3 both resolve assets
// correctly. See plans/RefinedPlans/001ImplementFrontend.md section 11.
export default defineConfig({
  plugins: [react()],
  base: '/report.html/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // One chunk keeps the standalone single-file build simple to inline, and
    // the whole app is small enough that splitting buys nothing here.
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})