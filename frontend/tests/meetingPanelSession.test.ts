import assert from 'node:assert/strict'
import test from 'node:test'

import { panelSession } from '../src/features/student/meetingSession.ts'
import type { StudentSession } from '../src/features/student/types.ts'

function session(
  id: string,
  status: StudentSession['status'],
  teamsMeetingId: string | null = null,
): StudentSession {
  return {
    id,
    course_code: 'CSIT321',
    title: `Class ${id}`,
    lecturer_id: 'lecturer-1',
    status,
    teams_meeting_id: teamsMeetingId,
  } as StudentSession
}

test('a running requested session is what the panel shows', () => {
  const old = session('old', 'ended', 'meeting-42')
  const asked = session('asked', 'active')
  assert.equal(panelSession([old, asked], 'asked', 'meeting-42')?.id, 'asked')
})

test('a finished requested session gives way to the meeting', () => {
  // Opened from a notification card for a class that has since finished. The
  // lecturer started the next one in the same meeting, so that is the class
  // the student is in now.
  const finished = session('finished', 'ended')
  const next = session('next', 'active', 'meeting-42')
  assert.equal(
    panelSession([finished, next], 'finished', 'meeting-42')?.id,
    'next',
  )
})

test('a finished requested session is kept when the meeting has nothing', () => {
  // Better to say the class is over than to show an empty panel.
  const finished = session('finished', 'ended')
  assert.equal(
    panelSession([finished], 'finished', 'meeting-42')?.id,
    'finished',
  )
})

test('the meeting session is used when no session was requested', () => {
  const ofMeeting = session('meeting-one', 'active', 'meeting-42')
  assert.equal(panelSession([ofMeeting], null, 'meeting-42')?.id, 'meeting-one')
})

test('nothing matches when the meeting holds no session', () => {
  const other = session('other', 'active', 'meeting-99')
  assert.equal(panelSession([other], null, 'meeting-42'), undefined)
})

test('a cancelled requested session also gives way to the meeting', () => {
  const cancelled = session('cancelled', 'cancelled')
  const next = session('next', 'active', 'meeting-42')
  assert.equal(
    panelSession([cancelled, next], 'cancelled', 'meeting-42')?.id,
    'next',
  )
})
