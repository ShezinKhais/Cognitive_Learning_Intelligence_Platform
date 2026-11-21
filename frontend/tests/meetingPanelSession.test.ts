import assert from 'node:assert/strict'
import test from 'node:test'

import { panelSession, shouldWatchMeeting } from '../src/features/student/meetingSession.ts'
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

test('the next class wins over a finished one still carrying the meeting id', () => {
  // The cached list is not refetched when a class ends, so both carry the
  // meeting's id, and the finished one is listed first.
  const finished = session('finished', 'ended', 'meeting-42')
  const next = session('next', 'active', 'meeting-42')
  assert.equal(panelSession([finished, next], null, 'meeting-42')?.id, 'next')
  assert.equal(panelSession([finished, next], 'finished', 'meeting-42')?.id, 'next')
})

test('a finished meeting session is still shown when it is all there is', () => {
  const finished = session('finished', 'ended', 'meeting-42')
  assert.equal(panelSession([finished], null, 'meeting-42')?.id, 'finished')
})

test('a class ended over the socket is watched until its successor is linked', () => {
  // The panel opened on a running class. The cached list still says active
  // after the lecturer ends it, so only the socket's report starts the watch.
  const none = new Set<string>()
  const running = session('first', 'active', 'meeting-42')
  assert.equal(panelSession([running], null, 'meeting-42')?.id, 'first')
  assert.equal(shouldWatchMeeting(true, 'meeting-42', running, none), false)

  const endedLive = new Set(['first'])
  assert.equal(shouldWatchMeeting(true, 'meeting-42', running, endedLive), true)

  // The refresh brings the ended class and the next one linked to the meeting.
  const ended = session('first', 'ended', 'meeting-42')
  const next = session('second', 'active', 'meeting-42')
  const shown = panelSession([ended, next], null, 'meeting-42')
  assert.equal(shown?.id, 'second')
  assert.equal(shouldWatchMeeting(true, 'meeting-42', shown, endedLive), false)
})

test('nothing is watched outside a ready Teams meeting', () => {
  const none = new Set<string>()
  assert.equal(shouldWatchMeeting(false, 'meeting-42', undefined, none), false)
  assert.equal(shouldWatchMeeting(true, null, undefined, none), false)
  assert.equal(shouldWatchMeeting(true, 'meeting-42', undefined, none), true)
})
