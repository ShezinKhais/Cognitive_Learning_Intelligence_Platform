import type { ReportStatus } from './sessionsApi.ts'

/** Which build button the report panel shows, if any. */
export type BuildButton = 'build' | 'retry' | 'again' | null

/**
 * Every state has a way forward. No job yet: build it. A job that failed,
 * or one whose progress could no longer be read (it is dropped then, since
 * nothing will move it on): try again. A finished report: build again.
 * Only a job still being built has no button.
 */
export function buildButton(status: ReportStatus | null): BuildButton {
  if (status === null) return 'build'
  if (status === 'failed') return 'retry'
  if (status === 'ready') return 'again'
  return null
}
