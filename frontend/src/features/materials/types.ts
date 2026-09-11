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
  visual_element_count?: number
  is_thin?: boolean
  is_visual_heavy?: boolean
}

/**
 * The fields through `uploaded_at` are the frozen MaterialOut contract.
 * `warnings` and `pages` are Phase 2 response fields shared with AI 1 and
 * BBIS. Defining them on both sides prevents the response model from silently
 * filtering the preview data before it reaches the client.
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
  warnings: string[]
  pages: MaterialPagePreview[]
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
