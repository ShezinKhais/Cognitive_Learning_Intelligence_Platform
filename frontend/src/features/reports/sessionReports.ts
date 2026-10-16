export type ReportStatus =
  | 'queued'
  | 'running'
  | 'ready'
  | 'failed'

export type ReportSessionStatus =
  | 'prepared'
  | 'active'
  | 'ending'
  | 'ended'
  | 'cancelled'

export interface ReportParticipation {
  students: number
  questions_delivered: number
  answers: number
  missed_answers: number
  attention_prompts: number
}

export type ReportTopicDifficultyLevel =
  | 'easy'
  | 'medium'
  | 'hard'

export interface ReportTopicDifficulty {
  topic: string
  questions: number
  answers: number
  mastered: number
  partial: number
  struggling: number
  uncertain: number
  score: number | null
  level: ReportTopicDifficultyLevel | null
  expected: ReportTopicDifficultyLevel | null
}

export interface ReportAlert {
  alert_id: string
  session_id: string
  question_id: string | null
  kind: string
  topic: string | null
  message: string
  reason: string
  confidence: number
  explanation: string
  explanation_source:
    | 'ai'
    | 'fallback'
  confidence_reasons: string[]
  recommendation: string
  status:
    | 'open'
    | 'acknowledged'
  raised_at: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  respondents: number | null
  threshold: number | null
  correct_ratio: number | null
}

export interface SessionReport {
  session_id: string
  course_code: string
  title: string
  status: ReportSessionStatus
  starts_at: string | null
  ended_at: string | null
  generated_at: string
  participation: ReportParticipation
  topics: ReportTopicDifficulty[]
  alerts: ReportAlert[]
}

export interface ReportJob {
  report_id: string
  session_id: string
  status: ReportStatus
  requested_at: string
  finished_at: string | null
  error: string | null
  message: string | null
  report: SessionReport | null
}

export const REPORT_POLL_MAX_FAILURES = 4

const REPORT_POLL_BASE_DELAY_MS = 2000
const REPORT_POLL_MAX_DELAY_MS = 10000

export function reportStatusLabel(
  status: ReportStatus,
): string {
  if (status === 'queued') {
    return 'Queued'
  }

  if (status === 'running') {
    return 'Generating'
  }

  if (status === 'ready') {
    return 'Ready'
  }

  return 'Failed'
}

export function reportIsReady(
  job: ReportJob,
): boolean {
  return (
    job.status === 'ready' &&
    job.report !== null
  )
}

export function reportFailureMessage(
  job: ReportJob,
): string | null {
  if (job.status !== 'failed') {
    return null
  }

  const message =
    job.message?.trim()

  if (message) {
    return message
  }

  return 'The report could not be generated.'
}

export function reportPollDelayMs(
  consecutiveFailures: number,
): number {
  const safeFailures =
    Math.max(
      0,
      Math.floor(
        consecutiveFailures,
      ),
    )

  return Math.min(
    REPORT_POLL_BASE_DELAY_MS *
      2 ** safeFailures,
    REPORT_POLL_MAX_DELAY_MS,
  )
}

export function reportShouldRetryPolling(
  consecutiveFailures: number,
): boolean {
  return (
    consecutiveFailures <
    REPORT_POLL_MAX_FAILURES
  )
}