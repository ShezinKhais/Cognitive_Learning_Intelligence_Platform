export type HistoryView = 'loading' | 'error' | 'empty' | 'ready'

interface HistoryRequest {
  failed: boolean
  history: { classes: readonly unknown[] } | null
}

/** One consistent state selection for the class-history panel. */
export function historyViewState(request: HistoryRequest): HistoryView {
  if (request.failed) return 'error'
  if (request.history === null) return 'loading'
  if (request.history.classes.length === 0) return 'empty'
  return 'ready'
}

/** A retry starts a new request rather than leaving the failed state stuck. */
export function nextHistoryAttempt(previous: number): number {
  return previous + 1
}
