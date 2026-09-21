import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const API_TARGET = process.env.SYLVASENSE_API ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Same-origin API in development: no CORS, no key material in the client.
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: { port: 4173, strictPort: true },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          // MapLibre is by far the largest dependency; splitting it keeps the
          // first paint of the shell fast.
          maplibre: ['maplibre-gl'],
          vendor: ['react', 'react-dom', '@tanstack/react-query', 'zustand'],
        },
      },
    },
  },
});
