import assert from 'node:assert/strict'
import test from 'node:test'

import { AI_SWITCHES, allOff, allOn, anyOn, matchesCourse, switchesOf } from '../src/features/live/aiControls.ts'
import { parseAiControls, parseSessionState } from '../src/features/student/liveSessionProtocol.ts'

test('there is one switch for each thing the lecturer can turn off', () => {
  assert.deepEqual(
    AI_SWITCHES.map((item) => item.key),
    ['auto_checkpoints', 'learning_assistant', 'refocus_nudges', 'engagement_estimates'],
  )
})

test('pause all turns every switch off, and any one on counts as on', () => {
  assert.equal(anyOn(allOff()), false)
  assert.equal(anyOn(allOn()), true)
  assert.equal(anyOn({ ...allOff(), refocus_nudges: true }), true)
})

test('the switches are compared with the course defaults, which are not sent back', () => {
  const view = { ...allOff(), course_defaults: allOff() }
  assert.equal(matchesCourse(view), true)
  assert.equal(matchesCourse({ ...view, learning_assistant: true }), false)
  assert.deepEqual(Object.keys(switchesOf(view)).sort(), [
    'auto_checkpoints', 'engagement_estimates', 'learning_assistant', 'refocus_nudges',
  ])
})

test('a switch the server does not send, or sends as something else, stays on', () => {
  assert.deepEqual(parseAiControls(undefined), allOn())
  assert.deepEqual(parseAiControls({ learning_assistant: false, refocus_nudges: 'no' }), {
    ...allOn(),
    learning_assistant: false,
  })
})

test('the session state carries the switches to the student page', () => {
  const state = parseSessionState({
    session_id: 's1',
    status: 'active',
    participant_count: 3,
    active_question_id: null,
    questions_delivered: 1,
    paused: false,
    ai: { ...allOn(), engagement_estimates: false },
  })
  assert.equal(state?.ai.engagement_estimates, false)
  assert.equal(state?.ai.learning_assistant, true)
})

test('pacing reads an empty box as the usual, and refuses numbers out of range', async () => {
  const { readPacing, pacingOf } = await import('../src/features/live/aiControls.ts')
  assert.deepEqual(readPacing('  ', 'checkpoint_minutes'), { value: null })
  assert.deepEqual(readPacing('10', 'checkpoint_minutes'), { value: 10 })
  assert.ok('error' in readPacing('2', 'checkpoint_minutes'))
  assert.ok('error' in readPacing('7.5', 'answer_seconds'))
  assert.ok('error' in readPacing('301', 'answer_seconds'))
  assert.deepEqual(pacingOf({}), { checkpoint_minutes: null, answer_seconds: null })
})
