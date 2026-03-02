import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // @ts-expect-error -- vitest config merged at runtime
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  server: {
    port: 5173,
    host: true,
    strictPort: true,
    fs: {
      strict: false
    },
    watch: {
      usePolling: false,
    }
  },
  optimizeDeps: {
    include: ['react', 'react-dom']
  }
})
