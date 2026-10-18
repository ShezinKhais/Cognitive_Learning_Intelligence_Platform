import assert from 'node:assert/strict'
import test from 'node:test'

import { buildButton } from '../src/features/sessions/reportControls.ts'

test('every report state offers a way forward except one still building', () => {
  assert.equal(buildButton(null), 'build')
  // A job that failed, and one dropped because its progress stopped answering.
  assert.equal(buildButton('failed'), 'retry')
  assert.equal(buildButton('ready'), 'again')
  assert.equal(buildButton('queued'), null)
  assert.equal(buildButton('running'), null)
})
