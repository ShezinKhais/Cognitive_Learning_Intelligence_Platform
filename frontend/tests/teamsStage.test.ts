import assert from 'node:assert/strict'
import test from 'node:test'

import {
  shareSessionToStage,
  simulatedStageHost,
  stageContentUrl,
  type StageHost,
} from '../src/teams/stage.ts'
import { simulatedTeamsContext } from '../src/teams/teamsContext.ts'

const SESSION = '11111111-1111-1111-1111-111111111111'

function host(overrides: Partial<StageHost> = {}): StageHost & { shared: string[] } {
  const shared: string[] = []
  return {
    shared,
    available: async () => true,
    share: async (url) => {
      shared.push(url)
      return true
    },
    ...overrides,
  }
}

test('the stage link is the meeting page for this session, on this origin', () => {
  assert.equal(
    stageContentUrl('https://clip.example', SESSION),
    `https://clip.example/teams/meeting?sessionId=${SESSION}`,
  )
})

test('only the origin is kept, so a path or query on it cannot redirect the stage', () => {
  assert.equal(
    stageContentUrl('https://clip.example/elsewhere?x=1#frag', SESSION),
    `https://clip.example/teams/meeting?sessionId=${SESSION}`,
  )
})

test('the session id is encoded and carries nothing else', () => {
  const url = stageContentUrl('https://clip.example', 'a b&c=d')
  assert.equal(url, 'https://clip.example/teams/meeting?sessionId=a+b%26c%3Dd')
})

test('Teams needs HTTPS, so anything else gives no link', () => {
  assert.equal(stageContentUrl('http://clip.example', SESSION), null)
  assert.equal(stageContentUrl('not a url', SESSION), null)
  assert.equal(stageContentUrl('https://clip.example', ''), null)
})

test('a meeting that allows it shares the link to the stage', async () => {
  const teams = host()
  assert.equal(await shareSessionToStage(teams, 'https://clip.example', SESSION), 'shared')
  assert.deepEqual(teams.shared, [`https://clip.example/teams/meeting?sessionId=${SESSION}`])
})

test('nothing is shared when the meeting does not allow it', async () => {
  const teams = host({ available: async () => false })
  assert.equal(await shareSessionToStage(teams, 'https://clip.example', SESSION), 'unavailable')
  assert.deepEqual(teams.shared, [])
})

test('nothing is shared from a page that is not on HTTPS', async () => {
  const teams = host()
  assert.equal(await shareSessionToStage(teams, 'http://localhost:5173', SESSION), 'unavailable')
  assert.deepEqual(teams.shared, [])
})

test('a refusal from Teams is reported, not treated as shared', async () => {
  const teams = host({ share: async () => false })
  assert.equal(await shareSessionToStage(teams, 'https://clip.example', SESSION), 'refused')
})

test('an error from Teams is reported as a failure', async () => {
  const teams = host({
    share: async () => {
      throw new Error('boom')
    },
  })
  assert.equal(await shareSessionToStage(teams, 'https://clip.example', SESSION), 'failed')
})

test('the simulation can show the stage frame, and nothing else is accepted as a frame', () => {
  assert.equal(simulatedTeamsContext('?teamsMock=1&frame=content').frameContext, 'content')
  assert.equal(simulatedTeamsContext('?teamsMock=1&frame=task').frameContext, 'task')
  assert.equal(simulatedTeamsContext('?teamsMock=1').frameContext, 'sidePanel')
  assert.equal(simulatedTeamsContext('?teamsMock=1&frame=evil').frameContext, 'sidePanel')
})

test('the simulated stage opens the stage frame for the same meeting and session', async () => {
  const opened: string[] = []
  const stage = simulatedStageHost((url) => opened.push(url), 'meeting-1')

  const result = await shareSessionToStage(stage, 'http://localhost:5173', SESSION, true)

  assert.equal(result, 'shared')
  const url = new URL(opened[0])
  assert.equal(url.origin, 'http://localhost:5173')
  assert.equal(url.pathname, '/teams/meeting')
  assert.equal(url.searchParams.get('sessionId'), SESSION)
  assert.equal(url.searchParams.get('frame'), 'content')
  assert.equal(url.searchParams.get('teamsMock'), '1')
  assert.equal(url.searchParams.get('meetingId'), 'meeting-1')
})

test('plain HTTP is still refused unless the simulation asks for it', async () => {
  const stage = simulatedStageHost(() => undefined, null)
  assert.equal(await shareSessionToStage(stage, 'http://localhost:5173', SESSION), 'unavailable')
})
