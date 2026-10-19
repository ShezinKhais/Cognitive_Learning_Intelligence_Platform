import assert from 'node:assert/strict'
import test from 'node:test'

import type { Material } from '../src/features/materials/types.ts'
import {
  materialWarnings,
  progressFromStatus,
  upsertMaterial,
  validateUpload,
} from '../src/features/materials/upload.ts'

function material(id: string, uploaded: string, overrides: Partial<Material> = {}): Material {
  return {
    id,
    filename: `${id}.pdf`,
    content_type: 'application/pdf',
    size_bytes: 1000,
    status: 'completed',
    page_count: 3,
    chunk_count: 4,
    error: null,
    uploaded_at: uploaded,
    ...overrides,
  }
}

test('only lecture formats under 50 MB are accepted', () => {
  assert.equal(validateUpload({ name: 'week1.pptx', size: 10 }), null)
  assert.match(validateUpload({ name: 'grades.xlsx', size: 10 }) ?? '', /PDF, PowerPoint/)
  assert.match(validateUpload({ name: 'empty.pdf', size: 0 }) ?? '', /empty/)
  assert.match(validateUpload({ name: 'huge.pdf', size: 51 * 1024 * 1024 }) ?? '', /50 MB/)
})

test('a stored status becomes the progress to show', () => {
  assert.equal(progressFromStatus(material('a', '2026-10-01T00:00:00Z')).stage, 'done')
  assert.equal(progressFromStatus(material('a', '2026-10-01T00:00:00Z', { status: 'failed', error: 'x' })).message, 'x')
  assert.equal(progressFromStatus(material('a', '2026-10-01T00:00:00Z', { status: 'processing' })).stage, 'validating')
})

test('a new or updated material sits in place, newest first', () => {
  const list = [material('old', '2026-10-01T00:00:00Z'), material('older', '2026-09-01T00:00:00Z')]
  const added = upsertMaterial(list, material('new', '2026-10-10T00:00:00Z', { status: 'processing' }))
  assert.deepEqual(added.map((m) => m.id), ['new', 'old', 'older'])
  const updated = upsertMaterial(added, material('new', '2026-10-10T00:00:00Z'))
  assert.deepEqual(updated.map((m) => [m.id, m.status]), [['new', 'completed'], ['old', 'completed'], ['older', 'completed']])
})

test('thin and image-heavy pages are named as warnings', () => {
  const warnings = materialWarnings(
    material('a', '2026-10-01T00:00:00Z', {
      warnings: ['Two slides had no text'],
      pages: [
        { page_number: 2, text: '', is_thin: true },
        { page_number: 5, text: 'chart', is_visual_heavy: true },
      ],
    }),
  )
  assert.deepEqual(warnings.map((w) => w.source_page), [undefined, 2, 5])
})
