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
