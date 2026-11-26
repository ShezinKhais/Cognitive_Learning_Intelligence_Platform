import { authenticatedFetch, statusMessage } from '../../api'
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
    throw new Error(
      `Could not access your private chat history. ${statusMessage(response.status)}`,
    )
  }

  return response
}

export async function listChatHistoryPage(
  limit = 100,
  offset = 0,
  signal?: AbortSignal,
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

  const response = await historyRequest(
    `${HISTORY_PATH}?${query.toString()}`,
    { signal },
  )

  return (await response.json()) as ChatHistoryPage
}

/** Read all pages, including records from earlier classes. */
export async function listAllChatHistory(
  signal?: AbortSignal,
): Promise<SavedChatExchange[]> {
  const items: SavedChatExchange[] = []
  const pageSize = 200

  while (true) {
    const page = await listChatHistoryPage(
      pageSize,
      items.length,
      signal,
    )

    items.push(...page.items)

    if (page.items.length === 0 || items.length >= page.total) {
      return items
    }

    if (page.items.length < pageSize) {
      throw new Error('Chat history pagination ended unexpectedly.')
    }
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
