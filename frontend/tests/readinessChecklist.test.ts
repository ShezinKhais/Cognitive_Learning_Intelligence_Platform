import assert from 'node:assert/strict'
import test from 'node:test'

import type { SessionReadiness } from '../src/features/live/sessionActions.ts'
import { readinessItems } from '../src/features/live/readinessItems.ts'

function readiness(overrides: Partial<SessionReadiness>): SessionReadiness {
  return {
    session_id: 's',
    ready: false,
    blockers: [],
    warnings: [],
    materials_total: 0,
    materials_processing: 0,
    materials_failed: 0,
    deliverable_questions: 0,
    checked_at: '2026-10-16T10:00:00Z',
    ...overrides,
  }
}

test('nothing uploaded points at materials for both steps', () => {
  const [material, questions] = readinessItems(readiness({}))
  assert.equal(material.done, false)
  assert.match(material.detail, /Upload/)
  assert.equal(questions.link?.label, 'Review questions')
})

test('a material still being read shows as working, not missing', () => {
  const [material] = readinessItems(readiness({ materials_total: 1, materials_processing: 1 }))
  assert.equal(material.working, true)
  assert.match(material.detail, /still being read/)
})

test('ready material and staged questions tick both and offer no link', () => {
  const items = readinessItems(readiness({ ready: true, materials_total: 2, materials_failed: 1, deliverable_questions: 4 }))
  assert.deepEqual(items.map((item) => item.done), [true, true])
  assert.match(items[0].detail, /1 could not be read/)
  assert.ok(items.every((item) => !item.link))
})
