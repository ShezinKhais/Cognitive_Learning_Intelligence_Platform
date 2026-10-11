import assert from 'node:assert/strict'
import test from 'node:test'

import {
  explanationSourceLabel,
  usableConfidenceReasons,
} from '../src/features/intelligence/intelligenceDisplay.ts'

test('AI explanation source has a clear lecturer label', () => {
  assert.equal(
    explanationSourceLabel('ai'),
    'AI explanation',
  )
})

test('fallback explanation source has a clear lecturer label', () => {
  assert.equal(
    explanationSourceLabel(
      'fallback',
    ),
    'Safe fallback explanation',
  )
})

test('missing explanation source is not invented', () => {
  assert.equal(
    explanationSourceLabel(undefined),
    'Explanation source unavailable',
  )

  assert.equal(
    explanationSourceLabel(null),
    'Explanation source unavailable',
  )
})

test('confidence reasons preserve authoritative backend text', () => {
  assert.deepEqual(
    usableConfidenceReasons([
      'Most responses were partial or struggling.',
      'Classifier confidence was high.',
    ]),
    [
      'Most responses were partial or struggling.',
      'Classifier confidence was high.',
    ],
  )
})

test('blank confidence reasons are ignored safely', () => {
  assert.deepEqual(
    usableConfidenceReasons([
      '',
      '   ',
      'Enough students responded.',
    ]),
    [
      'Enough students responded.',
    ],
  )
})

test('missing confidence reasons remain empty', () => {
  assert.deepEqual(
    usableConfidenceReasons(undefined),
    [],
  )

  assert.deepEqual(
    usableConfidenceReasons(null),
    [],
  )
})