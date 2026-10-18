import assert from 'node:assert/strict'
import test from 'node:test'

import { countByFilter, inFilter, shortcutFor, startingFilter } from '../src/features/review/reviewState.ts'

const q = (status: 'draft' | 'approved' | 'rejected' | 'staged' | 'delivered') => ({ status })

test('each question sits in one filter, and all of them in All', () => {
  const questions = [q('draft'), q('draft'), q('approved'), q('staged'), q('delivered'), q('rejected')]
  assert.deepEqual(countByFilter(questions), { review: 2, approved: 1, staged: 2, rejected: 1, all: 6 })
  assert.equal(inFilter(q('delivered'), 'staged'), true)
  assert.equal(inFilter(q('draft'), 'approved'), false)
})

test('review starts on what needs a decision, then shows everything', () => {
  assert.equal(startingFilter([q('approved'), q('draft')]), 'review')
  assert.equal(startingFilter([q('approved'), q('rejected')]), 'all')
})

test('only the documented keys are shortcuts', () => {
  assert.equal(shortcutFor('J'), 'next')
  assert.equal(shortcutFor('ArrowUp'), 'previous')
  assert.equal(shortcutFor('a'), 'approve')
  assert.equal(shortcutFor('s'), 'stage')
  assert.equal(shortcutFor('x'), null)
})
