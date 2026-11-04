import assert from 'node:assert/strict'
import test from 'node:test'

import { CrashBudget, MAX_REPORTS_PER_PAGE, crashMessage } from '../src/features/monitoring/crashReport.ts'

test('a report carries the error but no links, emails or tokens', () => {
  const message = crashMessage(
    new TypeError('failed for ada@uni.edu at https://x.test/a?b=1 with eyJabc.def.ghi'),
  )
  assert.equal(message, 'TypeError: failed for [email] at [url] with [token]')
})

test('a repeat is sent once and a page sends only a few', () => {
  const budget = new CrashBudget()
  assert.equal(budget.allow('render', 'a'), true)
  assert.equal(budget.allow('render', 'a'), false)
  for (let n = 1; n < MAX_REPORTS_PER_PAGE; n += 1) assert.equal(budget.allow('script', `m${n}`), true)
  assert.equal(budget.allow('script', 'one more'), false)
})
