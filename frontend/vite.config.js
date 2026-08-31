import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 端口 5173 若被占用，Vite 会自动切换到 5174，属正常现象
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5176,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
