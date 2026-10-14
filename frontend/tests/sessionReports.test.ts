import assert from 'node:assert/strict'
import test from 'node:test'

import {
  reportFailureMessage,
  reportIsReady,
  reportStatusLabel,
  type ReportJob,
} from '../src/features/reports/sessionReports.ts'

function reportJob(
  overrides: Partial<ReportJob> = {},
): ReportJob {
  return {
    report_id:
      '00000000-0000-0000-0000-000000000001',
    session_id:
      '00000000-0000-0000-0000-000000000002',
    status: 'queued',
    requested_at:
      '2026-10-14T10:00:00Z',
    finished_at: null,
    error: null,
    message: null,
    report: null,
    ...overrides,
  }
}

test('report status labels preserve backend states', () => {
  assert.equal(
    reportStatusLabel('queued'),
    'Queued',
  )

  assert.equal(
    reportStatusLabel('running'),
    'Generating',
  )

  assert.equal(
    reportStatusLabel('ready'),
    'Ready',
  )

  assert.equal(
    reportStatusLabel('failed'),
    'Failed',
  )
})

test('a report is downloadable only when the ready job contains the report', () => {
  assert.equal(
    reportIsReady(
      reportJob({
        status: 'ready',
        report: {
          session_id:
            '00000000-0000-0000-0000-000000000002',
          course_code: 'CSIT321',
          title: 'Capstone',
          status: 'ended',
          starts_at:
            '2026-10-14T09:00:00Z',
          ended_at:
            '2026-10-14T10:00:00Z',
          generated_at:
            '2026-10-14T10:05:00Z',
          participation: {
            students: 20,
            questions_delivered: 3,
            answers: 50,
            missed_answers: 10,
            attention_prompts: 2,
          },
          topics: [],
          alerts: [],
        },
      }),
    ),
    true,
  )

  assert.equal(
    reportIsReady(
      reportJob({
        status: 'ready',
        report: null,
      }),
    ),
    false,
  )

  assert.equal(
    reportIsReady(
      reportJob({
        status: 'running',
      }),
    ),
    false,
  )
})

test('failed jobs preserve the backend failure message', () => {
  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'failed',
        message:
          'Report generation was interrupted.',
      }),
    ),
    'Report generation was interrupted.',
  )
})

test('failed jobs use a safe fallback when no readable message exists', () => {
  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'failed',
        message: null,
      }),
    ),
    'The report could not be generated.',
  )

  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'failed',
        message: '   ',
      }),
    ),
    'The report could not be generated.',
  )
})

test('non-failed jobs do not invent an error message', () => {
  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'queued',
      }),
    ),
    null,
  )

  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'running',
      }),
    ),
    null,
  )

  assert.equal(
    reportFailureMessage(
      reportJob({
        status: 'ready',
      }),
    ),
    null,
  )
})