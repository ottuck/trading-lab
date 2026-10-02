import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 중에는 FastAPI(uvicorn :8000)로 API를 전달한다. 데모 DB용 API를 따로 띄우면 QL_API_URL로 바꾼다.
    proxy: { '/api': process.env.QL_API_URL ?? 'http://127.0.0.1:8000' },
  },
})
