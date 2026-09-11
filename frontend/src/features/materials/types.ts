export type MaterialStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'

export type MaterialStage =
  | 'validating'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'generating'
  | 'done'
  | 'failed'

export type WarningSeverity = 'info' | 'warning' | 'critical'

export interface MaterialWarning {
  code?: string
  message: string
  severity?: WarningSeverity
  source_page?: number
}

export interface MaterialPagePreview {
  page_number: number
  text: string
  word_count?: number
  image_count?: number
  is_thin?: boolean
  is_image_heavy?: boolean
}

/**
 * The fields through `uploaded_at` are the frozen MaterialOut contract.
 * `warnings` and `pages` are optional Phase 2 extensions used by the preview.
 * Keeping them optional lets the UI work while AI 1 and BBIS finalise their
 * persistence response without inventing client-side content.
 */
export interface Material {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  status: MaterialStatus
  page_count: number | null
  chunk_count: number | null
  error: string | null
  uploaded_at: string
  warnings?: Array<string | MaterialWarning>
  pages?: MaterialPagePreview[]
}

export interface MaterialProgress {
  material_id: string
  stage: MaterialStage
  percent: number
  message: string | null
}

export type ProgressConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'

export const PROCESSING_STAGES: Array<{
  key: Exclude<MaterialStage, 'failed'>
  label: string
}> = [
  { key: 'validating', label: 'Validating' },
  { key: 'extracting', label: 'Extracting' },
  { key: 'chunking', label: 'Chunking' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'generating', label: 'Generating' },
  { key: 'done', label: 'Complete' },
]
