import assert from 'node:assert/strict'
import test from 'node:test'

import {
  engagementCounts,
  engagementStatusLabel,
  evidenceCoverageLabel,
  shortStudentId,
} from '../src/features/attention/lecturerAttention.ts'

import type {
  LecturerEngagement,
} from '../src/features/attention/lecturerAttention.ts'

function student(
  status:
    LecturerEngagement['status'],
): LecturerEngagement {
  return {
    student_id:
      '12345678-1234-1234-1234-123456789abc',
    session_id:
      'session',
    score:
      status ===
      'insufficient_data'
        ? null
        : 0.5,
    status,
    confidence: 0.4,
    signals_available: [],
    computed_at:
      '2026-10-13T10:00:00Z',
  }
}

test(
  'engaged status keeps its backend meaning',
  () => {
    assert.equal(
      engagementStatusLabel(
        'engaged',
      ),
      'Engaged',
    )
  },
)

test(
  'at-risk status keeps its backend meaning',
  () => {
    assert.equal(
      engagementStatusLabel(
        'at_risk',
      ),
      'At risk',
    )
  },
)

test(
  'disengaged backend status uses non-judgemental lecturer wording',
  () => {
    assert.equal(
      engagementStatusLabel(
        'disengaged',
      ),
      'Needs attention',
    )
  },
)

test(
  'insufficient data remains explicit',
  () => {
    assert.equal(
      engagementStatusLabel(
        'insufficient_data',
      ),
      'Insufficient data',
    )
  },
)

test(
  'evidence coverage preserves the authoritative confidence value',
  () => {
    assert.equal(
      evidenceCoverageLabel(0),
      '0% coverage',
    )

    assert.equal(
      evidenceCoverageLabel(
        0.4,
      ),
      '40% coverage',
    )

    assert.equal(
      evidenceCoverageLabel(1),
      '100% coverage',
    )
  },
)

test(
  'missing or invalid evidence coverage remains unavailable',
  () => {
    assert.equal(
      evidenceCoverageLabel(
        null,
      ),
      'Coverage unavailable',
    )

    assert.equal(
      evidenceCoverageLabel(
        Number.NaN,
      ),
      'Coverage unavailable',
    )

    assert.equal(
      evidenceCoverageLabel(
        -0.1,
      ),
      'Coverage unavailable',
    )

    assert.equal(
      evidenceCoverageLabel(
        1.1,
      ),
      'Coverage unavailable',
    )
  },
)

test(
  'class counts preserve backend states while using privacy-safe presentation groups',
  () => {
    assert.deepEqual(
      engagementCounts([
        student('engaged'),
        student('engaged'),
        student('at_risk'),
        student(
          'disengaged',
        ),
        student(
          'insufficient_data',
        ),
      ]),
      {
        total: 5,
        engaged: 2,
        atRisk: 1,
        needsAttention: 1,
        insufficientData: 1,
      },
    )
  },
)

test(
  'student identifiers are shortened for display without changing the id',
  () => {
    assert.equal(
      shortStudentId(
        '12345678-1234-1234-1234-123456789abc',
      ),
      '12345678…',
    )

    assert.equal(
      shortStudentId(
        'abc',
      ),
      'abc',
    )

    assert.equal(
      shortStudentId(
        '   ',
      ),
      'Unavailable',
    )
  },
)