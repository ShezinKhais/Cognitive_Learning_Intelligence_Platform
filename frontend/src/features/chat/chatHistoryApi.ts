import { ApiError, authenticatedFetch, statusMessage } from '../../api'
import type { ChatCitation, ChatExchange } from './chatTypes'

/** A private exchange owned by the authenticated student. */
export interface SavedChatExchange {
  id: string
  request_id: string
  session_id: string | null
  question: string
  answer: string
  source: 'materials' | 'discussion'
  phase: ChatExchange['phase']
  citations: ChatCitation[]
  follow_ups: string[]
  general: boolean
  explanation: string | null
  created_at: string
}

export interface ChatHistoryPage {
  items: SavedChatExchange[]
  total: number
  limit: number
  offset: number
  next_before?: string | null
}

const HISTORY_PATH = '/me/chat-history'

async function historyRequest(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const response = await authenticatedFetch(path, {
    ...init,
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new ApiError(response.status, 'CHAT_HISTORY_REQUEST_FAILED', statusMessage(response.status))
  }

  return response
}

export function chatHistoryLoadMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'Saved conversations are unavailable on this server. Try again after the app is updated.'
    return error.message
  }
  return 'Your saved conversations could not be loaded. Check your connection and try again.'
}

export async function listChatHistoryPage(
  limit = 100,
  offset = 0,
  signal?: AbortSignal,
  sessionId?: string,
  before?: string,
): Promise<ChatHistoryPage> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
    throw new Error('Invalid history page size.')
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new Error('Invalid history offset.')
  }

  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })

  if (sessionId) query.set('session_id', sessionId)
  if (before) query.set('before', before)

  const response = await historyRequest(
    `${HISTORY_PATH}?${query.toString()}`,
    { signal },
  )

  return (await response.json()) as ChatHistoryPage
}

/**
 * Read the student's history using stable newest-first cursor pagination.
 * A newly saved or deleted record cannot shift an offset between pages.
 * The optional session filter keeps live chat restoration class-specific.
 */
export async function listAllChatHistory(
  signal?: AbortSignal,
  sessionId?: string,
): Promise<SavedChatExchange[]> {
  const items: SavedChatExchange[] = []
  const seenIds = new Set<string>()
  const usedCursors = new Set<string>()
  const pageSize = 200
  let before: string | undefined

  while (true) {
    const page = await listChatHistoryPage(
      pageSize,
      0,
      signal,
      sessionId,
      before,
    )

    for (const record of page.items) {
      if (seenIds.has(record.id)) continue
      seenIds.add(record.id)
      items.push(record)
    }

    // An empty page or a missing cursor marks the end of history.
    // Do not depend on a mutable total count to decide when to stop.
    if (page.items.length === 0 || !page.next_before) {
      return items
    }

    if (usedCursors.has(page.next_before) || page.next_before === before) {
      throw new Error('Chat history returned a repeated pagination cursor.')
    }

    usedCursors.add(page.next_before)
    before = page.next_before
  }
}

export async function deleteChatExchange(
  exchangeId: string,
): Promise<void> {
  await historyRequest(
    `${HISTORY_PATH}/${encodeURIComponent(exchangeId)}`,
    { method: 'DELETE' },
  )
}

export async function deleteAllChatHistory(): Promise<void> {
  await historyRequest(HISTORY_PATH, { method: 'DELETE' })
}

/** Convert a saved record back into the existing chat UI format. */
export function restoredExchange(
  saved: SavedChatExchange,
): ChatExchange {
  return {
    id: saved.request_id,
    question: saved.question,
    answer: saved.answer,
    phase: saved.phase,
    citations: saved.citations,
    followUps: saved.follow_ups,
    explanation: saved.explanation,
    general: saved.general,
  }
}
