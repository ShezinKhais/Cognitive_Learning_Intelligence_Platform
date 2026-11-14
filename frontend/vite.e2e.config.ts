import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { ortExternAlias } from './ortExternAlias'

// Separate entry/output: test controls never enter the application build.
export default defineConfig({
  define: { 'import.meta.env.VITE_SOCRATIC_CHAT_ENABLED': JSON.stringify('true') },
  plugins: [react(), tailwindcss(), {
    name: 'test-only-stream',
    config() {
      return { build: { rollupOptions: { input: ['e2e/question-bank/index.html'] } } }
    },
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
  resolve: { alias: ortExternAlias },
  build: { outDir: 'dist-e2e', rollupOptions: { input: ['e2e/review/index.html', 'e2e/harness/index.html', 'eval/attention-recorder.html', 'eval/gaze-demo.html', 'eval/vad-recorder.html'] } },
  preview: { host: '127.0.0.1', port: 4174, strictPort: true },
})
