import type {
  ChatAction,
  ChatExchange,
  ChatState,
  ChatStreamEvent,
} from './chatTypes'

/** The most earlier exchanges sent with a question; the server keeps the same. */
export const MAX_HISTORY = 3
const MAX_HISTORY_ANSWER = 1500

/**
 * What the tutor is told came before, so a follow-up has something to refer
 * to. Only answers that completed: a refused or stopped one is not something
 * the tutor said.
 */
export function historyFor(exchanges: readonly ChatExchange[]): { question: string; answer: string }[] {
  return exchanges
    .filter((exchange) => exchange.phase === 'completed' && exchange.answer.trim())
    .slice(-MAX_HISTORY)
    .map((exchange) => ({ question: exchange.question, answer: exchange.answer.slice(0, MAX_HISTORY_ANSWER) }))
}

/** An answer split into its text and the [n] citations in it. */
export function splitCitations(text: string): (string | number)[] {
  const parts: (string | number)[] = []
  let last = 0
  for (const match of text.matchAll(/\[(\d{1,2})\]/g)) {
    const at = match.index ?? 0
    if (at > last) parts.push(text.slice(last, at))
    parts.push(Number(match[1]))
    last = at + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export const initialChatState: ChatState = {
  phase: 'idle',
  draft: '',
  exchanges: [],
  activeId: null,
  error: null,
}

function updateActive(
  state: ChatState,
  requestId: string,
  update: (exchange: ChatExchange) => ChatExchange,
): ChatState {
  if (state.activeId !== requestId) return state

  return {
    ...state,
    exchanges: state.exchanges.map((exchange) =>
      exchange.id === requestId ? update(exchange) : exchange,
    ),
  }
}

function applyStreamEvent(
  state: ChatState,
  event: ChatStreamEvent,
): ChatState {
  if (event.type === 'error') {
    if (event.request_id && event.request_id !== state.activeId) return state
    return {
      ...state,
      phase: 'failed',
      activeId: null,
      error: event.detail,
      exchanges: state.exchanges.map((exchange) =>
        exchange.id === state.activeId
          ? { ...exchange, phase: 'failed' }
          : exchange,
      ),
    }
  }

  if (event.request_id !== state.activeId) return state

  switch (event.type) {
    case 'accepted':
      return state.phase === 'submitting'
        ? { ...state, phase: 'streaming' }
        : state
    case 'delta':
      return updateActive(
        { ...state, phase: 'streaming' },
        event.request_id,
        (exchange) => ({
          ...exchange,
          phase: 'streaming',
          answer: exchange.answer + event.text,
        }),
      )
    case 'citation':
      return updateActive(state, event.request_id, (exchange) => ({
        ...exchange,
        citations: exchange.citations.some(
          (citation) => citation.id === event.citation.id,
        )
          ? exchange.citations
          : [...exchange.citations, event.citation],
      }))
    case 'follow_up':
      return updateActive(state, event.request_id, (exchange) => ({
        ...exchange,
        followUps: exchange.followUps.includes(event.prompt)
          ? exchange.followUps
          : [...exchange.followUps, event.prompt],
      }))
    case 'unsupported':
      return {
        ...updateActive(state, event.request_id, (exchange) => ({
          ...exchange,
          phase: 'unsupported',
          explanation: event.reason,
        })),
        phase: 'unsupported',
        activeId: null,
      }
    case 'empty_retrieval':
      return {
        ...updateActive(state, event.request_id, (exchange) => ({
          ...exchange,
          phase: 'empty-retrieval',
          explanation:
            'I could not find relevant information in the lecture material for this session.',
        })),
        phase: 'empty-retrieval',
        activeId: null,
      }
    case 'completed':
      return {
        ...updateActive(state, event.request_id, (exchange) => ({
          ...exchange,
          phase: 'completed',
        })),
        phase: 'completed',
        activeId: null,
      }
    case 'cancelled':
      return {
        ...updateActive(state, event.request_id, (exchange) => ({
          ...exchange,
          phase: 'cancelled',
          explanation: 'You stopped this response before it was complete.',
        })),
        phase: 'cancelled',
        activeId: null,
      }
  }
}

export function chatReducer(
  state: ChatState,
  action: ChatAction,
): ChatState {
  switch (action.type) {
    case 'draft-changed':
      return { ...state, draft: action.value }
    case 'follow-up-selected':
      return { ...state, draft: action.prompt }
    case 'submit-started':
      if (state.activeId) return state
      return {
        ...state,
        phase: 'submitting',
        draft: '',
        activeId: action.id,
        error: null,
        exchanges: [
          ...state.exchanges,
          {
            id: action.id,
            question: action.question,
            answer: '',
            phase: 'streaming',
            citations: [],
            followUps: [],
            explanation: null,
          },
        ],
      }
    case 'stream-event':
      return applyStreamEvent(state, action.event)
    case 'cancel-started':
      return state.activeId ? { ...state, phase: 'cancelling' } : state
    case 'cancelled-locally':
      if (!state.activeId) return state
      return {
        ...state,
        phase: 'cancelled',
        activeId: null,
        exchanges: state.exchanges.map((exchange) =>
          exchange.id === state.activeId
            ? {
                ...exchange,
                phase: 'cancelled',
                explanation: 'You stopped this response before it was complete.',
              }
            : exchange,
        ),
      }
    case 'request-failed':
      return {
        ...state,
        phase: 'failed',
        activeId: null,
        error: action.detail,
        exchanges: state.exchanges.map((exchange) =>
          exchange.id === state.activeId
            ? { ...exchange, phase: 'failed' }
            : exchange,
        ),
      }
    case 'error-cleared':
      return { ...state, error: null }
  }
}
