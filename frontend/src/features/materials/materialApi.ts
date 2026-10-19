import {
  ApiError,
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
  apiUploadFile,
  authenticatedFetch,
} from '../../api'
import type { Material } from './types'

export function uploadMaterial(file: File): Promise<Material> {
  return apiUploadFile<Material>('/materials', file)
}

export function getMaterial(materialId: string): Promise<Material> {
  return apiAuthenticatedGet<Material>(`/materials/${materialId}`)
}

/** The caller's materials, newest first: a lecturer's own, every one for an
 * admin. */
export async function listMaterials(): Promise<Material[]> {
  const page = await apiAuthenticatedGet<{ items: Material[] }>('/materials?limit=200')
  return page.items
}

export interface MaterialChanges {
  filename?: string
  /** null files the material under no course. */
  course_code?: string | null
}

export function updateMaterial(materialId: string, changes: MaterialChanges): Promise<Material> {
  return apiAuthenticatedRequest<Material>(`/materials/${encodeURIComponent(materialId)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** Deletes the material. Answers 204 with no body, so it does not go
 * through the JSON request helper. */
export async function deleteMaterial(materialId: string): Promise<void> {
  const response = await authenticatedFetch(`/materials/${encodeURIComponent(materialId)}`, { method: 'DELETE' })
  if (response.ok) return
  let message = 'The material could not be deleted.'
  try {
    message = ((await response.json()) as { error?: { message?: string } }).error?.message ?? message
  } catch {
    // Not the API's error envelope.
  }
  throw new ApiError(response.status, 'DELETE_REFUSED', message)
}
