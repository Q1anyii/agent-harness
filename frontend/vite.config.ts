import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev 模式下通过 Vite proxy 把 /api 请求转发到后端 FastAPI（127.0.0.1:8000），
// 前端开发时无跨域问题；后端端口被占用时同步修改 target。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
