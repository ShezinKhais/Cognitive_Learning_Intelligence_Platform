import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { backendProxy } from './backendProxy.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'CLIP_')
  const proxy = backendProxy(process.env.CLIP_BACKEND_URL ?? env.CLIP_BACKEND_URL)
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy,
    },
    preview: { port: 4173, strictPort: true, proxy },
  }
})
