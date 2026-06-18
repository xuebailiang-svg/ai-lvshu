import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          maxSize: 450_000,
          groups: [
            { name: 'element-plus', test: /node_modules[\\/]element-plus/ },
            { name: 'vue-vendor', test: /node_modules[\\/](vue|vue-router|pinia)[\\/]/ },
            { name: 'markdown-vendor', test: /node_modules[\\/](marked|dompurify)[\\/]/ },
          ],
        },
      },
    },
  },
})
