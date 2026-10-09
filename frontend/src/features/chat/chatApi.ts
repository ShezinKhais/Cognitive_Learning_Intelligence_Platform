import {
  apiUrl,
  getAccessToken,
} from '../../api'
import { parseNdjsonLine } from './chatProtocol'
import type { ChatStreamEvent } from './chatTypes'

export const MAX_CHAT_QUESTION_LENGTH = 2000

export interface ChatRequest {
  sessionId: string
  requestId: string
  question: string
  signal: AbortSignal
  onEvent: (event: ChatStreamEvent) => void
}

export async function streamChat(request: ChatRequest): Promise<void> {
  const token = getAccessToken()
  if (!token) throw new Error('Login is required.')

  const response = await fetch(
    apiUrl(`/sessions/${encodeURIComponent(request.sessionId)}/chat`),
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'application/x-ndjson',
      },
      body: JSON.stringify({
        request_id: request.requestId,
        question: request.question,
      }),
      signal: request.signal,
    },
  )

  if (!response.ok) {
    let detail = `The tutor could not respond (HTTP ${response.status}).`
    try {
      const body = await response.json()
      detail = body?.error?.message ?? detail
    } catch {
      // A proxy error page is not expected to contain the API envelope.
    }
    throw new Error(detail)
  }

  if (!response.body) throw new Error('The tutor returned no response stream.')

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let terminal = false

  function deliver(event: ChatStreamEvent): void {
    if (
      event.type === 'completed' ||
      event.type === 'cancelled' ||
      event.type === 'unsupported' ||
      event.type === 'empty_retrieval' ||
      event.type === 'error'
    ) terminal = true
    request.onEvent(event)
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event = parseNdjsonLine(line)
      if (!event) throw new Error('The tutor returned an invalid stream event.')
      deliver(event)
    }
  }

  if (buffer.trim()) {
    const event = parseNdjsonLine(buffer)
    if (!event) throw new Error('The tutor returned an incomplete stream event.')
    deliver(event)
  }

  if (!terminal) throw new Error('The tutor response ended before it was complete.')
}
