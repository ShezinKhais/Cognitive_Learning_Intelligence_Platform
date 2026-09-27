import assert from 'node:assert/strict'
import test from 'node:test'

import {
  normalizeTheme,
  simulatedTeamsContext,
} from '../src/teams/teamsContext.ts'
import { buildSessionNotificationCard } from '../src/teams/notificationCard.ts'
import { meetingTabConfiguration } from '../src/teams/configuration.ts'
import { applyTeamsTheme } from '../src/teams/teamsTheme.ts'

test('normalizes supported Teams themes and safely falls back', () => {
  assert.equal(normalizeTheme('dark'), 'dark')
  assert.equal(normalizeTheme('contrast'), 'contrast')
  assert.equal(normalizeTheme('glass'), 'glass')
  assert.equal(normalizeTheme('unexpected'), 'default')
  assert.equal(normalizeTheme(undefined), 'default')
})

test('builds a simulated meeting side-panel context from the URL', () => {
  const context = simulatedTeamsContext(
    '?teamsMock=1&meetingId=meeting-42&userId=user-7&theme=contrast',
  )

  assert.equal(context.meetingId, 'meeting-42')
  assert.equal(context.userId, 'user-7')
  assert.equal(context.theme, 'contrast')
  assert.equal(context.frameContext, 'sidePanel')
})

test('applies exactly one Teams theme class', () => {
  const values = new Set<string>(['dark'])
  const root = {
    classList: {
      add: (...classes: string[]) => classes.forEach((value) => values.add(value)),
      remove: (...classes: string[]) => classes.forEach((value) => values.delete(value)),
    },
    dataset: {} as Record<string, string>,
  } as unknown as HTMLElement

  applyTeamsTheme('contrast', root)

  assert.deepEqual([...values], ['contrast'])
  assert.equal(root.dataset.teamsTheme, 'contrast')

  applyTeamsTheme('default', root)
  assert.deepEqual([...values], [])
})

test('builds an Adaptive Card linked to the authorized session route', () => {
  const card = buildSessionNotificationCard({
    sessionId: 'session/42',
    courseCode: 'CSIT321',
    title: 'Live lecture',
    appBaseUrl: 'https://clip.example/',
  })

  assert.equal(card.type, 'AdaptiveCard')
  const actions = card.actions as Array<Record<string, string>>
  assert.equal(actions[0]?.type, 'Action.OpenUrl')
  assert.equal(
    actions[0]?.url,
    'https://clip.example/teams/meeting?sessionId=session%2F42',
  )
})

test('configures the meeting tab to open the student side panel', () => {
  assert.deepEqual(
    meetingTabConfiguration('https://clip.example/config'),
    {
      entityId: 'clip.meeting',
      contentUrl: 'https://clip.example/teams/meeting',
      websiteUrl: 'https://clip.example/teams/meeting',
      suggestedDisplayName: 'C.L.I.P',
    },
  )
})
