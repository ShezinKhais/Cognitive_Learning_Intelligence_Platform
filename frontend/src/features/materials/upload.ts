import type { Material, MaterialProgress, MaterialStage, MaterialWarning } from './types'

export const ACCEPTED_EXTENSIONS = ['pdf', 'pptx', 'docx', 'txt'] as const
export const ACCEPT_ATTRIBUTE = '.pdf,.pptx,.docx,.txt'
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export function fileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

/** Why a file cannot be uploaded, or null when it can. */
export function validateUpload(file: Pick<File, 'name' | 'size'>): string | null {
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(fileExtension(file.name))) {
    return 'Choose a PDF, PowerPoint, Word or plain-text file.'
  }
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) return 'That file is larger than 50 MB.'
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** What the processing stage means for the lecturer, in their words. */
export const STAGE_WORDS: Record<MaterialStage, string> = {
  validating: 'Checking the file',
  extracting: 'Reading the pages',
  chunking: 'Splitting it into sections',
  embedding: 'Indexing it for the tutor',
  generating: 'Drafting questions',
  done: 'Ready to review',
  failed: 'Could not be processed',
}

/** The progress to show for a material before any live update arrives. */
export function progressFromStatus(material: Material): MaterialProgress {
  if (material.status === 'completed') {
    return { material_id: material.id, stage: 'done', percent: 100, message: null }
  }
  if (material.status === 'failed') {
    return { material_id: material.id, stage: 'failed', percent: 100, message: material.error }
  }
  return { material_id: material.id, stage: 'validating', percent: 5, message: null }
}

export function isFinished(material: Pick<Material, 'status'>): boolean {
  return material.status === 'completed' || material.status === 'failed'
}

export function sourceName(material: Pick<Material, 'filename'>): 'Slide' | 'Page' {
  return fileExtension(material.filename) === 'pptx' ? 'Slide' : 'Page'
}

/** The material's own warnings, then one for each thin or image-heavy page. */
export function materialWarnings(material: Material): MaterialWarning[] {
  const supplied = (material.warnings ?? []).map((message) => ({ message, severity: 'warning' as const }))
  const pages = (material.pages ?? []).flatMap((page) => {
    const found: MaterialWarning[] = []
    if (page.is_thin) {
      found.push({
        code: 'THIN_CONTENT',
        message: 'Very little readable text here.',
        severity: 'warning',
        source_page: page.page_number,
      })
    }
    if (page.is_visual_heavy) {
      found.push({
        code: 'IMAGE_HEAVY',
        message: 'Mostly images. Check the text read from it before approving its questions.',
        severity: 'warning',
        source_page: page.page_number,
      })
    }
    return found
  })
  return [...supplied, ...pages]
}

/** Newest first, with one material replaced or added. */
export function upsertMaterial(materials: readonly Material[], material: Material): Material[] {
  const rest = materials.filter((item) => item.id !== material.id)
  return [material, ...rest].sort((a, b) => Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at))
}
