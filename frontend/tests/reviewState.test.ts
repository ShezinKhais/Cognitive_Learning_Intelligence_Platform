import assert from 'node:assert/strict'
import test from 'node:test'

import { countByFilter, inFilter, shortcutFor, startingFilter } from '../src/features/review/reviewState.ts'

const q = (status: 'draft' | 'approved' | 'rejected' | 'staged' | 'delivered') => ({ status })

test('each question sits in one filter, and all of them in All', () => {
  const questions = [q('draft'), q('draft'), q('approved'), q('staged'), q('delivered'), q('rejected')]
  // An 'approved' row from before approving made it ready counts as ready.
  assert.deepEqual(countByFilter(questions), { review: 2, staged: 3, rejected: 1, all: 6 })
  assert.equal(inFilter(q('delivered'), 'staged'), true)
  assert.equal(inFilter(q('approved'), 'staged'), true)
  assert.equal(inFilter(q('draft'), 'staged'), false)
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
