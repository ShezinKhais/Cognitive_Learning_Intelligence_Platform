import type {
  ChatCitation,
  ChatStreamEvent,
} from './chatTypes'

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function nonEmpty(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function nullableNumber(value: unknown): number | null | undefined {
  return value === null ? null : typeof value === 'number' ? value : undefined
}

function citation(value: unknown): ChatCitation | null {
  const item = record(value)
  if (!item) return null

  const id = nonEmpty(item.id)
  const materialTitle = nonEmpty(item.material_title)
  const sourcePage = nullableNumber(item.source_page)
  const sourceSlide = nullableNumber(item.source_slide)
  const excerpt = item.excerpt === null ? null : nonEmpty(item.excerpt)

  if (
    !id ||
    !materialTitle ||
    sourcePage === undefined ||
    sourceSlide === undefined ||
    excerpt === undefined
  ) return null

  return {
    id,
    material_title: materialTitle,
    source_page: sourcePage,
    source_slide: sourceSlide,
    excerpt,
  }
}

export function parseChatStreamEvent(value: unknown): ChatStreamEvent | null {
  const item = record(value)
  if (!item) return null

  const type = nonEmpty(item.type)
  const requestId = item.request_id === null ? null : nonEmpty(item.request_id)
  if (!type || requestId === null && type !== 'error') return null

  switch (type) {
    case 'accepted':
    case 'completed':
    case 'cancelled':
      return requestId ? { type, request_id: requestId } : null
    case 'delta': {
      const text = typeof item.text === 'string' ? item.text : null
      return requestId && text !== null
        ? { type, request_id: requestId, text }
        : null
    }
    case 'citation': {
      const parsed = citation(item.citation)
      return requestId && parsed
        ? { type, request_id: requestId, citation: parsed }
        : null
    }
    case 'follow_up': {
      const prompt = nonEmpty(item.prompt)
      return requestId && prompt
        ? { type, request_id: requestId, prompt }
        : null
    }
    case 'unsupported': {
      const reason = nonEmpty(item.reason)
      return requestId && reason
        ? { type, request_id: requestId, reason }
        : null
    }
    case 'empty_retrieval':
      return requestId ? { type, request_id: requestId } : null
    case 'error': {
      const detail = nonEmpty(item.detail)
      return detail
        ? { type, request_id: requestId, detail }
        : null
    }
    default:
      return null
  }
}

export function parseNdjsonLine(line: string): ChatStreamEvent | null {
  try {
    return parseChatStreamEvent(JSON.parse(line))
  } catch {
    return null
  }
}
