import { ApiError, apiAuthenticatedRequest } from '../../api'

import type { MyDeletionRequest } from './myDeletion'

export { isOpen, type DeletionStatus, type MyDeletionRequest } from './myDeletion'

/** Everything C.L.I.P keeps about the signed-in student, as JSON. */
export function exportMyData(): Promise<Record<string, unknown>> {
  return apiAuthenticatedRequest('/me/data', { cache: 'no-store' })
}

/** The latest erasure request, or null when the student never asked. */
export async function getMyDeletionRequest(signal?: AbortSignal): Promise<MyDeletionRequest | null> {
  try {
    return await apiAuthenticatedRequest<MyDeletionRequest>('/me/deletion-request', { cache: 'no-store', signal })
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      return null
    }
    throw caught
  }
}

export function requestMyDeletion(reason: string | null): Promise<MyDeletionRequest> {
  return apiAuthenticatedRequest('/me/deletion-request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true, reason }),
  })
}

/** Saves a JSON value as a file through the browser. */
export function saveJson(value: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  try {
    link.href = url
    link.download = filename
    document.body.append(link)
    link.click()
  } finally {
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
