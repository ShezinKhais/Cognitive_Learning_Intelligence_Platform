import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canApproveDeletion,
  canExecuteDeletion,
  canRejectDeletion,
  deletionStatusLabel,
  deletionTargetLabel,
  type DeletionRequest,
} from '../src/features/governance/governance.ts'

function deletionRequest(
  overrides:
    Partial<DeletionRequest> = {},
): DeletionRequest {
  return {
    request_id:
      '00000000-0000-0000-0000-000000000001',
    target_type: 'session',
    target_id:
      '00000000-0000-0000-0000-000000000002',
    status: 'requested',
    reason: null,
    requested_by:
      '00000000-0000-0000-0000-000000000003',
    requested_at:
      '2026-10-14T10:00:00Z',
    decided_by: null,
    decided_at: null,
    executed_by: null,
    executed_at: null,
    outcome: null,
    ...overrides,
  }
}

test('deletion status labels preserve backend states', () => {
  assert.equal(
    deletionStatusLabel(
      'requested',
    ),
    'Requested',
  )

  assert.equal(
    deletionStatusLabel(
      'approved',
    ),
    'Approved',
  )

  assert.equal(
    deletionStatusLabel(
      'rejected',
    ),
    'Rejected',
  )

  assert.equal(
    deletionStatusLabel(
      'executed',
    ),
    'Executed',
  )
})

test('deletion target labels do not invent additional target types', () => {
  assert.equal(
    deletionTargetLabel(
      'session',
    ),
    'Session',
  )

  assert.equal(
    deletionTargetLabel(
      'student',
    ),
    'Student',
  )
})

test('the admin who requested deletion cannot approve their own request', () => {
  const request =
    deletionRequest({
      requested_by:
        'admin-one',
    })

  assert.equal(
    canApproveDeletion(
      request,
      'admin-one',
    ),
    false,
  )

  assert.equal(
    canApproveDeletion(
      request,
      'admin-two',
    ),
    true,
  )
})

test('only requested deletions can be rejected', () => {
  assert.equal(
    canRejectDeletion(
      deletionRequest({
        status: 'requested',
      }),
    ),
    true,
  )

  assert.equal(
    canRejectDeletion(
      deletionRequest({
        status: 'approved',
      }),
    ),
    false,
  )
})

test('only approved session requests can be executed', () => {
  assert.equal(
    canExecuteDeletion(
      deletionRequest({
        status: 'approved',
        target_type: 'session',
      }),
    ),
    true,
  )

  assert.equal(
    canExecuteDeletion(
      deletionRequest({
        status: 'requested',
        target_type: 'session',
      }),
    ),
    false,
  )

  assert.equal(
    canExecuteDeletion(
      deletionRequest({
        status: 'approved',
        target_type: 'student',
      }),
    ),
    false,
  )
})
