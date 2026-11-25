import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { liveAssistantVisible } from '../src/features/student/liveAssistantVisibility.ts'

test('live assistant starts consistently on web and Teams', () => {
  assert.equal(liveAssistantVisible(true, true, 'active', false), true)
  assert.equal(liveAssistantVisible(true, true, 'prepared', false), true)
})

test('lecturer can disable chat on every surface', () => {
  assert.equal(liveAssistantVisible(true, false, 'active', false), false)
})

test('deployment can disable chat on every surface', () => {
  assert.equal(liveAssistantVisible(false, true, 'active', false), false)
})

test('ended and cancelled sessions hide the live assistant', () => {
  assert.equal(liveAssistantVisible(true, true, 'ended', false), false)
  assert.equal(liveAssistantVisible(true, true, 'cancelled', false), false)
})

test('Teams checkpoint dialog stays checkpoint-only', () => {
  assert.equal(liveAssistantVisible(true, true, 'active', true), false)
})

test('Teams and normal web use the same live session panel', () => {
  const teams = readFileSync(
    new URL('../src/pages/TeamsMeetingPage.tsx', import.meta.url),
    'utf8',
  )

  const live = readFileSync(
    new URL('../src/pages/StudentLiveSessionPage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(teams, /<LiveSessionPanel/)
  assert.match(live, /liveAssistantVisible\(/)
  assert.match(live, /<SocraticChatPanel/)
})

test('chat tab separates discussion notes from the assistant', () => {
  const live = readFileSync(
    new URL('../src/pages/StudentLiveSessionPage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(live, /hidden=\{assistant && activeView === 'chat'\}/)
})