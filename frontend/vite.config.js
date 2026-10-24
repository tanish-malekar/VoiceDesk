import { defineConfig } from 'vite';

export default defineConfig({
  build: { rollupOptions: { input: { caller: 'index.html', operator: 'operator.html' } } },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
