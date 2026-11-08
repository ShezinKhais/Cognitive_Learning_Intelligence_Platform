import { apiAuthenticatedRequest, getAccessToken } from '../../api'
import { crashArea, type CrashKind } from './crashReport'

const reported = new Set<CrashKind>()

/** Tell the admins a page crashed. Only for a signed-in user; never throws. */
export function reportCrash(kind: CrashKind): void {
  if (!getAccessToken()) return
  if (reported.has(kind)) return
  reported.add(kind)
  apiAuthenticatedRequest('/client-errors', {
    method: 'POST',
    keepalive: true,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, page: crashArea(window.location.pathname) }),
  }).catch(() => undefined)
}

/** Report crashes that no error boundary sees. */
export function watchForCrashes(): void {
  window.addEventListener('error', () => reportCrash('script'))
  window.addEventListener('unhandledrejection', () => reportCrash('promise'))
}
