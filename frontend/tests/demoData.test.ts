import assert from 'node:assert/strict'
import test from 'node:test'

import { formGroups, SAMPLE_STUDENTS, seeded } from '../src/features/demos/sampleData.ts'

test('groups keep everyone, once each', () => {
  const groups = formGroups(SAMPLE_STUDENTS, 4, 7)
  assert.equal(groups.flat().length, SAMPLE_STUDENTS.length)
  assert.equal(new Set(groups.flat()).size, SAMPLE_STUDENTS.length)
})

test('nobody is left in a group of one', () => {
  for (let size = 2; size <= 6; size += 1) {
    const groups = formGroups(Array.from({ length: 13 }, (_, i) => i), size, 3)
    assert.ok(groups.every((group) => group.length >= 2), `size ${size}`)
  }
})

test('the same seed gives the same groups', () => {
  assert.deepEqual(formGroups(SAMPLE_STUDENTS, 3, 11), formGroups(SAMPLE_STUDENTS, 3, 11))
  assert.equal(seeded(1)(), seeded(1)())
})
