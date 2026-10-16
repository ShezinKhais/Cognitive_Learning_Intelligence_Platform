import {
  apiAuthenticatedGet,
  apiUploadFile,
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
