import { defineConfig } from 'vite';
export default defineConfig({
  base: './',
  worker: { format: 'es' },
  build: { target: 'es2022', chunkSizeWarningLimit: 800 },
  // DepthWizard: forward API calls to the local FastAPI backend during development.
  server: { strictPort: true, port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  clearScreen: false,
});
