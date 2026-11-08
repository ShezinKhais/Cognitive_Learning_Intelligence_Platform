import { apiAuthenticatedGet } from '../../api'

export interface SessionEngagement {
  session_id: string
  title: string
  course_code: string
  held_at: string
  present: number
  checkpoints: number
  /** 0 to 1, or null with no checkpoints. */
  answer_rate: number | null
  correct_rate: number | null
  /** Only when three or more students turned the indicator on. */
  on_screen: number | null
}

export interface QuietStudent {
  student_id: string
  name: string
  course_code: string
  sessions_considered: number
  sessions_missed: number
  answer_rate: number | null
}

export interface EngagementHistory {
  sessions: SessionEngagement[]
  quiet: QuietStudent[]
  recent_window: number
}

export function getEngagementHistory(): Promise<EngagementHistory> {
  return apiAuthenticatedGet('/engagement-history')
}
