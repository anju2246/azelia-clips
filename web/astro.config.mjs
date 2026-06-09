// @ts-check
import { defineConfig } from 'astro/config';

import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

// https://astro.build/config
export default defineConfig({
  integrations: [react()],

  vite: {
    server: {
      watch: {
        usePolling: true,
      },
      hmr: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          ws: true, // forward the job-status WebSocket (/api/ws/jobs/...) in dev
        },
      },
    },
    optimizeDeps: {
      force: true,
    },
    plugins: [
      tailwindcss(),
    ]
  }
});
