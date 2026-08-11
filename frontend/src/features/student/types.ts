export type ConsentType =
  | 'terms'
  | 'engagement_monitoring'
  | 'camera'
  | 'microphone'

export interface StudentUser {
  id: string
  email: string
  full_name: string
  role: 'student'
  consents: ConsentType[]
}

export type SessionStatus =
  | 'prepared'
  | 'active'
  | 'ending'
  | 'ended'
  | 'cancelled'

export interface StudentSession {
  id: string
  course_code: string
  title: string
  lecturer_id: string
  status: SessionStatus
  starts_at: string | null
  ended_at: string | null
  teams_meeting_id: string | null
  participant_count: number
  questions_delivered: number
}