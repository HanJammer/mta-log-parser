import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The build is served by Quart under `PATH_PREFIX/static/app/`. The prefix is only known at run
 * time, so index.html is built with the literal `__MLP_PREFIX__` and the backend replaces it when
 * serving the page (see README.md). Everything referenced from JS and CSS is emitted with relative
 * URLs, so the placeholder only ever appears in index.html.
 */
export const PREFIX_PLACEHOLDER = '__MLP_PREFIX__';

const backend = process.env.MLP_BACKEND ?? 'http://localhost:8487';

/** Vite forces a leading "/" on `base`; drop it so `__MLP_PREFIX__` → '' or '/logs' yields valid URLs. */
const prefixPlaceholder: Plugin = {
  name: 'mlp-prefix-placeholder',
  enforce: 'post',
  transformIndexHtml(html) {
    return html.split(`/${PREFIX_PLACEHOLDER}/`).join(`${PREFIX_PLACEHOLDER}/`);
  },
};

export default defineConfig(({ command }) => ({
  base: command === 'build' ? `${PREFIX_PLACEHOLDER}/static/app/` : '/',
  plugins: [react(), prefixPlaceholder],
  server: {
    port: 5180,
    proxy: {
      '/api': { target: backend },
    },
  },
  experimental: {
    renderBuiltUrl(_filename, { hostType }) {
      if (hostType === 'js' || hostType === 'css') return { relative: true };
      return undefined;
    },
  },
  build: {
    outDir: '../mlp/static/app',
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/ },
            { name: 'xlsx', test: /node_modules[\\/]xlsx[\\/]/ },
            { name: 'vendor', test: /node_modules[\\/]/ },
          ],
        },
      },
    },
  },
}));
