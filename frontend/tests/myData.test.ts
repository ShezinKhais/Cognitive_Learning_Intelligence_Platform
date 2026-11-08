import assert from 'node:assert/strict'
import test from 'node:test'

import { isOpen, type MyDeletionRequest } from '../src/features/student/myDeletion.ts'

function request(status: MyDeletionRequest['status']): MyDeletionRequest {
  return { request_id: 'r', status, requested_at: '2026-11-01T00:00:00Z', decided_at: null, executed_at: null }
}

test('a waiting or approved erasure request blocks asking again', () => {
  assert.equal(isOpen(request('requested')), true)
  assert.equal(isOpen(request('approved')), true)
})

test('no request, a rejected one or a finished one lets the student ask', () => {
  assert.equal(isOpen(null), false)
  assert.equal(isOpen(request('rejected')), false)
  assert.equal(isOpen(request('executed')), false)
})
