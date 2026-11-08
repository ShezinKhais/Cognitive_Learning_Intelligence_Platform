import assert from 'node:assert/strict'
import test from 'node:test'

import {
  reachNotice,
  teamsUpdatePagePath,
  teamsUpdatesPath,
  updateAge,
  updateKindLabel,
} from '../src/teams/lecturerUpdates.ts'

test('the lecturer is told how many students checkpoints will not pop up for', () => {
  assert.equal(
    reachNotice({ students_on_course: 20, students_in_teams: 17 }),
    "3 students have not opened C.L.I.P in Teams yet, so checkpoints will not pop up for them. Ask the class to open it once from the meeting's side panel.",
  )
  assert.match(reachNotice({ students_on_course: 2, students_in_teams: 1 }) ?? '', /^1 student has/)
})

test('nothing is said when everyone is reachable, nobody is enrolled, or Teams is off', () => {
  assert.equal(reachNotice({ students_on_course: 5, students_in_teams: 5 }), null)
  assert.equal(reachNotice({ students_on_course: 0, students_in_teams: 0 }), null)
  assert.equal(reachNotice({ students_on_course: 5, students_in_teams: null }), null)
})

test('the update paths name the session safely', () => {
  assert.equal(teamsUpdatesPath('a/b'), '/meetings/sessions/a%2Fb/updates')
  assert.equal(teamsUpdatePagePath('s 1'), '/lecturer/teams/update?sessionId=s%201')
})

test('an update says how long ago it came and what kind it is', () => {
  const now = Date.parse('2026-11-08T10:10:00Z')
  assert.equal(updateAge('2026-11-08T10:09:50Z', now), 'just now')
  assert.equal(updateAge('2026-11-08T10:07:00Z', now), '3 min ago')
  assert.equal(updateAge('not a date', now), '')
  assert.equal(updateKindLabel('checkpoint'), 'Checkpoint')
  assert.equal(updateKindLabel('attention'), 'Engagement')
  assert.equal(updateKindLabel('something new'), 'Update')
})
