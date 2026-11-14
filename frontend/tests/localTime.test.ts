import assert from 'node:assert/strict'
import test from 'node:test'

import { fromLocalInput, toLocalInput } from '../src/features/sessions/localTime.ts'

test('a local input round-trips through ISO', () => {
  const local = '2030-01-02T09:30'
  const iso = fromLocalInput(local)
  assert.ok(iso)
  assert.equal(toLocalInput(iso), local)
})

test('empty or broken values give nothing', () => {
  assert.equal(fromLocalInput(''), null)
  assert.equal(fromLocalInput('not a date'), null)
  assert.equal(toLocalInput(null), '')
  assert.equal(toLocalInput('nonsense'), '')
})
