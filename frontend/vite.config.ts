import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 중에는 FastAPI(uvicorn :8000)로 API를 전달한다.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
