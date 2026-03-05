// @ts-check
import { defineConfig } from 'astro/config';

import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

import { VitePWA } from 'vite-plugin-pwa';

// https://astro.build/config
export default defineConfig({
  integrations: [react()],

  vite: {
    server: {
      watch: {
        usePolling: true, // Forces faster reloads
      },
      hmr: true, // Force Hot Module Replacement
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    optimizeDeps: {
      force: true, // Disables Vite pre-bundling cache
    },
    plugins: [
      tailwindcss(),
      VitePWA({
        disable: process.env.NODE_ENV === 'development', // KILL aggressive offline caching in DEV
        registerType: 'autoUpdate',
        manifest: {
          name: 'Celia Clips',
          short_name: 'Celia',
          description: 'AI-powered podcast clip generator',
          theme_color: '#09090b',
          background_color: '#09090b',
          display: 'standalone',
          icons: [
            {
              src: 'pwa-192x192.png',
              sizes: '192x192',
              type: 'image/png'
            },
            {
              src: 'pwa-512x512.png',
              sizes: '512x512',
              type: 'image/png'
            }
          ]
        },
        workbox: {
          globPatterns: ['**/*.{js,css,html,ico,png,svg}']
        }
      })
    ]
  }
});