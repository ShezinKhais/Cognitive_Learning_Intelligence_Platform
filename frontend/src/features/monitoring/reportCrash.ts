import { apiAuthenticatedRequest, getAccessToken } from '../../api'
import { CrashBudget, crashMessage, type CrashKind } from './crashReport'

const budget = new CrashBudget()

/** Tell the admins a page crashed. Only for a signed-in user; never throws. */
export function reportCrash(kind: CrashKind, error: unknown): void {
  if (!getAccessToken()) return
  const message = crashMessage(error)
  if (!budget.allow(kind, message)) return
  apiAuthenticatedRequest('/client-errors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, message, page: window.location.pathname.slice(0, 200) || '/' }),
  }).catch(() => undefined)
}

/** Report crashes that no error boundary sees. */
export function watchForCrashes(): void {
  window.addEventListener('error', (event) => reportCrash('script', event.error ?? event.message))
  window.addEventListener('unhandledrejection', (event) => reportCrash('promise', event.reason))
}
