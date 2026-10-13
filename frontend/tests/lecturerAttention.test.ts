import assert from 'node:assert/strict'
import test from 'node:test'

import {
  engagementConfidenceLabel,
  engagementCounts,
  engagementScoreLabel,
  engagementStatusLabel,
  shortStudentId,
  signalLabel,
} from '../src/features/attention/lecturerAttention.ts'

import type {
  LecturerEngagement,
} from '../src/features/attention/lecturerAttention.ts'

function student(
  status: LecturerEngagement['status'],
): LecturerEngagement {
  return {
    student_id:
      '12345678-1234-1234-1234-123456789abc',
    session_id: 'session',
    score:
      status === 'insufficient_data'
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
  'engagement status labels preserve backend meaning',
  () => {
    assert.equal(
      engagementStatusLabel(
        'engaged',
      ),
      'Engaged',
    )

    assert.equal(
      engagementStatusLabel(
        'at_risk',
      ),
      'At risk',
    )

    assert.equal(
      engagementStatusLabel(
        'disengaged',
      ),
      'Disengaged',
    )

    assert.equal(
      engagementStatusLabel(
        'insufficient_data',
      ),
      'Insufficient data',
    )
  },
)

test(
  'engagement score formats an authoritative zero-to-one value',
  () => {
    assert.equal(
      engagementScoreLabel(0),
      '0%',
    )

    assert.equal(
      engagementScoreLabel(0.674),
      '67%',
    )

    assert.equal(
      engagementScoreLabel(1),
      '100%',
    )
  },
)

test(
  'missing or invalid score remains unavailable',
  () => {
    assert.equal(
      engagementScoreLabel(null),
      'Unavailable',
    )

    assert.equal(
      engagementScoreLabel(
        Number.NaN,
      ),
      'Unavailable',
    )

    assert.equal(
      engagementScoreLabel(-0.1),
      'Unavailable',
    )

    assert.equal(
      engagementScoreLabel(1.1),
      'Unavailable',
    )
  },
)

test(
  'confidence is shown as evidence coverage without changing the status',
  () => {
    assert.equal(
      engagementConfidenceLabel(0.4),
      '40% confidence',
    )

    assert.equal(
      engagementConfidenceLabel(null),
      'Confidence unavailable',
    )
  },
)

test(
  'signal names receive privacy-safe lecturer labels',
  () => {
    assert.equal(
      signalLabel('attempt_rate'),
      'Checkpoint participation',
    )

    assert.equal(
      signalLabel('response_timing'),
      'Response timing',
    )

    assert.equal(
      signalLabel('prompt_response'),
      'Attention check response',
    )

    assert.equal(
      signalLabel('gaze'),
      'Camera-facing estimate',
    )

    assert.equal(
      signalLabel(
        'face_presence',
      ),
      'Face presence',
    )
  },
)

test(
  'unknown signals are not given invented meaning',
  () => {
    assert.equal(
      signalLabel(
        'future_signal',
      ),
      'Other available signal',
    )
  },
)

test(
  'class counts preserve each authoritative backend status',
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
        disengaged: 1,
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
      shortStudentId('abc'),
      'abc',
    )

    assert.equal(
      shortStudentId('   '),
      'Unavailable',
    )
  },
)