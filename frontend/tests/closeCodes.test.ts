import assert from 'node:assert/strict'
import test from 'node:test'

import { actionForClose } from '../src/features/materials/closeCodes.ts'

test('a refused token sends the lecturer to sign in', () => {
  assert.equal(actionForClose(4001), 'sign-in')
})

test('a refusal that retrying cannot fix stops the reconnect loop', () => {
  assert.equal(actionForClose(4003), 'stop')
  assert.equal(actionForClose(4400), 'stop')
})

test('anything that can succeed next time is retried', () => {
  for (const code of [1000, 1006, 1011, 1013, 4408]) {
    assert.equal(actionForClose(code), 'retry', `close code ${code}`)
  }
})
