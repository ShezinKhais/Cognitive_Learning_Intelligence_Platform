import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('consent page distinguishes student indicators from lecturer transcription', () => {
  const source = readFileSync(
    new URL('../src/pages/ConsentPage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /Student camera and microphone engagement indicators/)
  assert.match(source, /lecturer/)
  assert.match(source, /Short audio chunks/)
  assert.match(source, /unreviewed transcript/)
  assert.match(source, /separate permissions/)
})

test('privacy page explains stored transcripts and Teams drafts', () => {
  const source = readFileSync(
    new URL('../src/pages/PrivacyPage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /Live lecturer microphone transcription/)
  assert.match(source, /automatically shared/)
  assert.match(source, /Teams transcripts and discussion minutes/)
  assert.match(source, /Private draft summaries/)
})
