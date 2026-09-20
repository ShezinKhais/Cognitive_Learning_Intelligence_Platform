import type {
  AnswerReceipt,
  AttentionPrompt,
  FeedbackResult,
  LiveErrorEvent,
  LiveQuestion,
  QuestionClosedEvent,
  ReadyEvent,
  ServerEvent,
  SessionStateEvent,
} from './liveSessionTypes'

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function parseServerEvent(value: unknown): ServerEvent | null {
  if (!isRecord(value)) return null
  if (typeof value.type !== 'string') return null
  if (!isNumber(value.seq) || value.seq < 0) return null
  if (typeof value.ts !== 'string') return null

  return {
    type: value.type,
    seq: value.seq,
    ts: value.ts,
    data: value.data,
  }
}

export function parseReady(value: unknown): ReadyEvent | null {
  if (!isRecord(value)) return null
  if (typeof value.user_id !== 'string') return null
  if (!isStringOrNull(value.session_id)) return null
  if (value.resumed_from_seq !== null && !isNumber(value.resumed_from_seq)) return null
  if (!isStringOrNull(value.stream_id)) return null

  return value as unknown as ReadyEvent
}

export function parseSessionState(value: unknown): SessionStateEvent | null {
  if (!isRecord(value)) return null
  if (typeof value.session_id !== 'string') return null
  if (!['prepared', 'active', 'ending', 'ended', 'cancelled'].includes(String(value.status))) {
    return null
  }
  if (!isNumber(value.participant_count) || !isNumber(value.questions_delivered)) return null
  if (!isStringOrNull(value.active_question_id)) return null

  return value as unknown as SessionStateEvent
}

export function parseLiveQuestion(value: unknown): LiveQuestion | null {
  if (!isRecord(value)) return null
  if (typeof value.question_id !== 'string' || typeof value.prompt !== 'string') return null
  if (!isStringOrNull(value.closes_at) || value.closes_at === null) return null
  if (!isNumber(value.window_seconds) || value.window_seconds <= 0) return null
  if (value.options !== null && (
    !Array.isArray(value.options) || !value.options.every((option) => typeof option === 'string')
  )) return null
  if (value.source_slide !== null && !isNumber(value.source_slide)) return null

  return value as unknown as LiveQuestion
}

export function parseQuestionClosed(value: unknown): QuestionClosedEvent | null {
  if (!isRecord(value) || typeof value.question_id !== 'string') return null
  if (!['window_elapsed', 'lecturer_closed', 'session_ended'].includes(String(value.reason))) {
    return null
  }
  if (!isNumber(value.respondents) || !isNumber(value.eligible)) return null

  return value as unknown as QuestionClosedEvent
}

export function parseAnswerReceipt(value: unknown): AnswerReceipt | null {
  if (!isRecord(value) || typeof value.question_id !== 'string') return null
  if (typeof value.accepted !== 'boolean' || typeof value.received_at !== 'string') return null
  if (!isStringOrNull(value.reason)) return null

  return value as unknown as AnswerReceipt
}

export function parseFeedbackResult(value: unknown): FeedbackResult | null {
  if (!isRecord(value) || typeof value.question_id !== 'string') return null
  if (value.correct !== null && typeof value.correct !== 'boolean') return null
  if (!isStringOrNull(value.explanation)) return null
  if (value.source_slide !== null && !isNumber(value.source_slide)) return null

  return value as unknown as FeedbackResult
}

export function parseAttentionPrompt(value: unknown): AttentionPrompt | null {
  if (!isRecord(value)) return null
  if (typeof value.prompt_id !== 'string' || typeof value.message !== 'string') return null
  if (typeof value.expires_at !== 'string' || !isNumber(value.escalation)) return null

  return value as unknown as AttentionPrompt
}

export function parseLiveError(value: unknown): LiveErrorEvent | null {
  if (!isRecord(value) || typeof value.code !== 'string') return null
  if (!isStringOrNull(value.detail)) return null

  return value as unknown as LiveErrorEvent
}
