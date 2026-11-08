import assert from 'node:assert/strict'
import test from 'node:test'

import { crashArea } from '../src/features/monitoring/crashReport.ts'

test('crash reports use a known area without student IDs or unknown path segments', () => {
  assert.equal(crashArea('/student/private-answer'), '/student')
  assert.equal(crashArea('/ada@example.test/private-answer'), '/')
  assert.equal(crashArea('/'), '/')
})
