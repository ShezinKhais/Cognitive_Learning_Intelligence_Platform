import type { SessionStatus } from './types'

export type LiveConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'recovering'
  | 'reconnecting'
  | 'offline'
  | 'forbidden'
  | 'ended'
  | 'disconnected'

export type QuestionCloseReason =
  | 'window_elapsed'
  | 'lecturer_closed'
  | 'session_ended'

export interface SessionStateEvent {
  session_id: string
  status: SessionStatus
  participant_count: number
  active_question_id: string | null
  questions_delivered: number
  paused: boolean
}

export interface LiveQuestion {
  question_id: string
  prompt: string
  options: string[] | null
  closes_at: string
  window_seconds: number
  source_slide: number | null
}

export interface QuestionClosedEvent {
  question_id: string
  reason: QuestionCloseReason
  respondents: number
  eligible: number
}

export interface AnswerReceipt {
  question_id: string
  accepted: boolean
  received_at: string
  reason: string | null
}

export interface FeedbackResult {
  question_id: string
  correct: boolean | null
  explanation: string | null
  source_slide: number | null
}

export interface AttentionPrompt {
  prompt_id: string
  message: string
  expires_at: string
  escalation: number
}

export interface ReadyEvent {
  user_id: string
  session_id: string | null
  resumed_from_seq: number | null
  stream_id: string | null
}

export interface LiveErrorEvent {
  code: string
  detail: string | null
}

export interface ServerEvent {
  type: string
  seq: number
  ts: string
  data: unknown
}

export type CheckpointPhase =
  | 'answering'
  | 'submitting'
  | 'submitted'
  | 'rejected'
  | 'missed'

export interface CheckpointState {
  question: LiveQuestion
  phase: CheckpointPhase
  selectedOption: number | null
  freeText: string
  receipt: AnswerReceipt | null
  feedback: FeedbackResult | null
  closed: QuestionClosedEvent | null
}
