export type ChatPhase =
  | 'idle'
  | 'submitting'
  | 'streaming'
  | 'cancelling'
  | 'completed'
  | 'cancelled'
  | 'unsupported'
  | 'empty-retrieval'
  | 'failed'

export interface ChatCitation {
  id: string
  material_title: string
  source_page: number | null
  source_slide: number | null
  excerpt: string | null
}

export interface ChatExchange {
  id: string
  question: string
  answer: string
  phase: Exclude<ChatPhase, 'idle' | 'submitting'>
  citations: ChatCitation[]
  followUps: string[]
  explanation: string | null
}

export interface ChatState {
  phase: ChatPhase
  draft: string
  exchanges: ChatExchange[]
  activeId: string | null
  error: string | null
}

export type ChatStreamEvent =
  | { type: 'accepted'; request_id: string }
  | { type: 'delta'; request_id: string; text: string }
  | { type: 'citation'; request_id: string; citation: ChatCitation }
  | { type: 'follow_up'; request_id: string; prompt: string }
  | { type: 'unsupported'; request_id: string; reason: string }
  | { type: 'empty_retrieval'; request_id: string }
  | { type: 'completed'; request_id: string }
  | { type: 'cancelled'; request_id: string }
  | { type: 'error'; request_id: string | null; detail: string }

export type ChatAction =
  | { type: 'draft-changed'; value: string }
  | { type: 'submit-started'; id: string; question: string }
  | { type: 'stream-event'; event: ChatStreamEvent }
  | { type: 'cancel-started' }
  | { type: 'cancelled-locally' }
  | { type: 'request-failed'; detail: string }
  | { type: 'follow-up-selected'; prompt: string }
  | { type: 'error-cleared' }

