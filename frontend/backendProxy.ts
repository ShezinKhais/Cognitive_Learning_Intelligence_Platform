/** Server-side only: browsers always use same-origin /api and /ws URLs. */
export function backendProxy(value = 'http://localhost:8000') {
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('CLIP_BACKEND_URL must be an HTTP(S) origin without credentials or a path')
  }
  return {
    '/api': { target: url.origin, changeOrigin: true },
    '/ws': { target: url.origin, changeOrigin: true, ws: true },
  }
}
