import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';


const apiProxyTarget = process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000';
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': apiProxyTarget,
      '/health': apiProxyTarget,
    },
  },
});
