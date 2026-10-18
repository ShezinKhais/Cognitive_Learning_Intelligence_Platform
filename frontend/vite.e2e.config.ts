import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Separate entry/output: test controls never enter the application build.
export default defineConfig({
  plugins: [react(), tailwindcss(), {
    name: 'test-only-stream',
    configurePreviewServer(server) {
      server.middlewares.use('/api/v1/sessions/phase8/chat', (req, res) => {
        let body = ''
        req.on('data', chunk => { body += chunk })
        req.on('end', () => {
          const { request_id } = JSON.parse(body)
          res.writeHead(200, { 'Content-Type': 'application/x-ndjson' })
          const send = (event: object) => res.write(JSON.stringify({ ...event, request_id }) + '\n')
          send({ type: 'accepted' })
          send({ type: 'delta', text: 'Start with the first principle. ' })
          const timer = setTimeout(() => {
            send({ type: 'delta', text: 'Which assumption would you check?' })
            send({ type: 'completed' })
            res.end()
          }, 30_000)
          res.on('close', () => clearTimeout(timer))
        })
      })
    },
  }],
  build: { outDir: 'dist-e2e', rollupOptions: { input: ['e2e/harness/index.html', 'eval/attention-recorder.html'] } },
  preview: { host: '127.0.0.1', port: 4174, strictPort: true },
})
