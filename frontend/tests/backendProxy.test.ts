import assert from 'node:assert/strict'
import { createServer as createHttpServer, request } from 'node:http'
import { once } from 'node:events'
import type { AddressInfo } from 'node:net'
import { test } from 'node:test'
import { createServer, preview, resolveConfig } from 'vite'
import { backendProxy } from '../backendProxy.ts'

test('one backend origin routes REST and live/progress WebSockets together', () => {
  const proxy = backendProxy('https://example.test:8443')
  assert.equal(proxy['/api'].target, 'https://example.test:8443')
  assert.equal(proxy['/ws'].target, proxy['/api'].target)
  assert.equal(proxy['/ws'].ws, true)
  assert.equal(backendProxy()['/api'].target, 'http://localhost:8000')
  for (const invalid of ['ws://example.test', 'https://user:secret@example.test',
    'https://example.test/api', 'https://example.test?token=x', 'https://example.test/#x']) {
    assert.throws(() => backendProxy(invalid))
  }
})

test('the real Vite config keeps dev and preview on the same backend', async () => {
  const config = await resolveConfig({}, 'serve')
  assert.deepEqual(config.server.proxy, config.preview.proxy)
  assert.equal(config.server.strictPort, true)
  assert.equal(config.preview.strictPort, true)
})

for (const mode of ['dev', 'preview'] as const) {
  test(`${mode} forwards API bodies, authorization and WebSocket upgrades to a custom port`, async () => {
    const upstream = createHttpServer(async (req, res) => {
      let body = ''
      for await (const chunk of req) body += chunk
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ path: req.url, auth: req.headers.authorization, body }))
    })
    upstream.on('upgrade', (req, socket) => {
      socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nX-Upstream-Path: ' + req.url + '\r\n\r\n')
    })
    upstream.listen(0, '127.0.0.1')
    await once(upstream, 'listening')
    const target = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`
    const proxy = backendProxy(target)
    let closeFrontend: (() => Promise<void>) | undefined
    try {
      const options = { configFile: false as const, logLevel: 'silent' as const,
        server: { host: '127.0.0.1', port: 0, proxy },
        preview: { host: '127.0.0.1', port: 0, proxy },
        build: { outDir: 'tests' } }
      let port: number
      if (mode === 'dev') {
        const server = await createServer(options)
        closeFrontend = () => server.close()
        await server.listen()
        port = (server.httpServer!.address() as AddressInfo).port
      } else {
        const server = await preview(options)
        closeFrontend = () => new Promise<void>((resolve, reject) => {
          server.httpServer.close(error => error ? reject(error) : resolve())
          server.httpServer.closeAllConnections()
        })
        port = (server.httpServer.address() as AddressInfo).port
      }
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/sessions/example/chat`, {
        method: 'POST', headers: { Authorization: 'Bearer test-only' }, body: 'question',
      })
      assert.equal(response.status, 200)
      assert.deepEqual(await response.json(), { path: '/api/v1/sessions/example/chat',
        auth: 'Bearer test-only', body: 'question' })
      await new Promise<void>((resolve, reject) => {
        const req = request({ host: '127.0.0.1', port, path: '/ws/session',
          headers: { Connection: 'Upgrade', Upgrade: 'websocket' } })
        req.setTimeout(5000, () => req.destroy(new Error('WebSocket upgrade timed out')))
        req.on('upgrade', (res, socket) => {
          socket.destroy()
          try {
            assert.equal(res.statusCode, 101)
            assert.equal(res.headers['x-upstream-path'], '/ws/session')
            resolve()
          } catch (error) { reject(error) }
        })
        req.on('response', res => { res.resume(); reject(new Error(`Upgrade refused: ${res.statusCode}`)) })
        req.on('error', reject)
        req.end()
      })
    } finally {
      await closeFrontend?.()
      upstream.closeAllConnections()
      await new Promise<void>(resolve => upstream.close(() => resolve()))
    }
  })
}
