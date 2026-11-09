import assert from 'node:assert/strict'
import test from 'node:test'

import { opensForQuestion, paperclipLabel, paperclipScore } from '../src/features/student/paperclip.ts'

test('the closed clip says how many checkpoints the student has answered', () => {
  assert.equal(paperclipLabel(2, 5, false), 'C.L.I.P. 2 of 5 checkpoints answered.')
  assert.equal(paperclipScore(2, 5), '2/5')
})

test('before any checkpoint there is no score to show', () => {
  assert.equal(paperclipLabel(0, 0, false), 'C.L.I.P. No checkpoints yet.')
  assert.equal(paperclipScore(0, 0), '')
})

test('a waiting question is announced to a screen reader', () => {
  assert.match(paperclipLabel(1, 3, true), /A question is waiting/)
})

test('the clip opens for a new question', () => {
  assert.equal(opensForQuestion(null, 'q1'), true)
  assert.equal(opensForQuestion('q1', 'q2'), true)
})

test('the clip stays as the student left it for the same question, or none', () => {
  assert.equal(opensForQuestion('q1', 'q1'), false)
  assert.equal(opensForQuestion('q1', null), false)
  assert.equal(opensForQuestion(null, null), false)
})
