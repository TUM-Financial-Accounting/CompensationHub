import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // Observable Plot + d3 is most of the bundle (~200 kB gzipped) and the shell needs it, so one chunk.
  build: { chunkSizeWarningLimit: 700 },
})
