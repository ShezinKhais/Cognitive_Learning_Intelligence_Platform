import { ApiError } from '../../api'
import {
  reportPollDelayMs,
  reportShouldRetryPolling,
  type ReportJob,
} from './sessionReports'

export const MAX_REPORT_POLL_ATTEMPTS = 60

export interface ReportPollingOptions {
  reportId: string
  sessionId: string
  currentSessionId: () => string | undefined
  getFailures: () => number
  setFailures: (count: number) => void
  fetchReport: (reportId: string) => Promise<ReportJob>
  onJob: (job: ReportJob) => void
  onError: (message: string | null) => void
  onStop: () => void
  onMissing: () => void
  onUnauthenticated: () => void
  setTimer: (callback: () => void, delayMs: number) => number
  clearTimer: (timer: number) => void
}

/**
 * Run the same status polling used by the report page, with injectable clock
 * and API boundaries so retries and access failures can be tested.
 */
export function startReportPolling(options: ReportPollingOptions): () => void {
  let active = true
  let timer: number | undefined
  let attempts = 0

  const isCurrent = () =>
    active && options.currentSessionId() === options.sessionId

  function schedule(delayMs: number): void {
    if (!isCurrent()) return

    timer = options.setTimer(() => {
      timer = undefined
      void poll()
    }, delayMs)
  }

  async function poll(): Promise<void> {
    if (!isCurrent()) return

    attempts++

    try {
      const updated = await options.fetchReport(options.reportId)
      if (!isCurrent()) return

      if (updated.session_id !== options.sessionId) {
        options.onStop()
        options.onError(
          'The report response did not match the current session. Automatic status checks have stopped.',
        )
        return
      }

      options.setFailures(0)
      options.onJob(updated)
      options.onError(null)

      if (updated.status === 'queued' || updated.status === 'running') {
        if (attempts >= MAX_REPORT_POLL_ATTEMPTS) {
          active = false
          options.onStop()
          options.onError(
            'The report is still being generated. Automatic status checks have stopped. Use Refresh to check again.',
          )
          return
        }

        schedule(reportPollDelayMs(0))
      }
    } catch (caught: unknown) {
      if (!isCurrent()) return

      if (caught instanceof ApiError && caught.status === 401) {
        options.onUnauthenticated()
        return
      }

      if (caught instanceof ApiError && caught.status === 404) {
        options.onMissing()
        options.onStop()
        options.onError(
          'This report is no longer available. It may have expired or the server may have restarted. Generate the report again.',
        )
        return
      }

      if (caught instanceof ApiError && caught.status === 403) {
        options.onStop()
        options.onError(
          `${caught.message} Automatic status checks have stopped. Use Refresh if your access changes.`,
        )
        return
      }

      const failures = options.getFailures() + 1
      options.setFailures(failures)

      if (!reportShouldRetryPolling(failures)) {
        options.onStop()
        options.onError(
          'The report status could not be refreshed after several attempts. Automatic status checks have stopped. Use Refresh to try again.',
        )
        return
      }

      options.onError(
        caught instanceof ApiError
          ? `${caught.message} The page will retry automatically.`
          : 'The report status could not be refreshed. The page will retry automatically.',
      )

      schedule(reportPollDelayMs(failures))
    }
  }

  schedule(reportPollDelayMs(options.getFailures()))

  return () => {
    active = false
    if (timer !== undefined) options.clearTimer(timer)
  }
}
