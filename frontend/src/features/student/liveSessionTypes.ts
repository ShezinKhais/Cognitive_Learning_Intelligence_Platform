
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

/** The lecturer's AI switches for the class. Each is on unless turned off. */
export interface AiControls {
  auto_checkpoints: boolean
  learning_assistant: boolean
  refocus_nudges: boolean
  engagement_estimates: boolean
}

export interface SessionStateEvent {
  session_id: string
  status: SessionStatus
  participant_count: number
  active_question_id: string | null
  questions_delivered: number
  paused: boolean
  ai: AiControls
}

/** Word and text files are numbered by section, PowerPoint by slide. */
export type SourceLabel = 'Page' | 'Slide' | 'Section'

/** "Section 3", or "Slide 3" when the server did not say. */
export function sourcePlace(label: SourceLabel | null | undefined, number: number): string {
  return `${label ?? 'Slide'} ${number}`
}

export interface LiveQuestion {
  question_id: string
  prompt: string
  options: string[] | null
  closes_at: string
  window_seconds: number
  source_slide: number | null
  /** What source_slide numbers. Older servers leave it out. */
  source_label?: SourceLabel | null
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
  source_label?: SourceLabel | null
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
  | 'unconfirmed'
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
