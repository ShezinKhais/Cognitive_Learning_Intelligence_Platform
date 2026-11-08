import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const automaticOff = { configured: false, enabled: false, subscribed: false, message: 'Automatic fetching disabled.', drafts: [], pending: 0, failed: 0 }
const noteId = '27f347a5-1595-4448-9244-b6849b51e936'
const noteTime = '2026-11-01T10:30:00Z'
test.beforeEach(async ({ page }) => {
  await page.route('**/live-transcription', route => route.fulfill({ json: { configured: false, running: false, session_running: true, capture_id: null, language: 'en' } }))
})

const initial = { note_id: noteId, text: 'Normalization reduces duplicate database values.', occurred_at: noteTime, updated_at: noteTime }

test('lecturer confirms, publishes, corrects and removes course minutes', async ({ page }) => {
  let notes: typeof initial[] = []
  const writes: Record<string, unknown>[] = []
  await page.route('**/api/v1/sessions/discussion-session/discussion**', async route => {
    const request = route.request()
    if (request.url().endsWith('/automatic-transcripts')) return route.fulfill({ json: automaticOff })
    if (request.url().endsWith('/transcripts')) return route.fulfill({ json: { enabled: false, items: [], message: 'Import disabled.' } })
    if (request.method() === 'PUT') {
      const body = request.postDataJSON()
      writes.push(body)
      const note = { ...body, note_id: request.url().split('/').at(-1), updated_at: noteTime }
      notes = [note]
      return route.fulfill({ json: note })
    }
    if (request.method() === 'DELETE') {
      notes = []
      return route.fulfill({ json: { removed: true } })
    }
    return route.fulfill({ json: { notes, latest_recorded_at: notes[0]?.occurred_at ?? null, session_status: 'active' } })
  })
  await page.goto('/e2e/harness/index.html?socket=discussion&publisher')
  await expect(page.getByText('No discussion notes have been published.', { exact: false })).toBeVisible()
  await page.getByLabel('Minutes to share with the course').fill(initial.text)
  await expect(page.getByRole('button', { name: 'Publish note' })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'I reviewed these minutes', exact: false }).check()
  await page.getByRole('button', { name: 'Publish note' }).click()
  await page.getByText('Read session record (1)').click()
  await expect(page.getByText(initial.text, { exact: true })).toBeVisible()
  expect(writes[0].shareable_confirmed).toBe(true)
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await page.getByLabel('Minutes to share with the course').fill('Corrected teaching point.')
  await page.getByRole('checkbox', { name: 'I reviewed these minutes', exact: false }).check()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Corrected teaching point.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Remove published note' }).click()
  await page.getByRole('button', { name: 'Confirm removal' }).click()
  await expect(page.getByText('No discussion notes have been published.', { exact: false })).toBeVisible()
})

test('ended-session catch-up sends a time window and opens the full cited minutes', async ({ page }) => {
  await page.route('**/api/v1/sessions/discussion-session/discussion', route => route.fulfill({ json: {
    notes: [initial], latest_recorded_at: noteTime, session_status: 'ended',
  } }))
  let question: Record<string, unknown> | undefined
  await page.route('**/api/v1/sessions/discussion-session/chat', route => {
    question = route.request().postDataJSON()
    return route.fulfill({ contentType: 'application/x-ndjson', body: [
      { type: 'accepted' },
      { type: 'delta', text: 'The discussion covered normalization. [1]' },
      { type: 'citation', citation: { id: noteId, source_note_id: noteId, number: 1, material_title: 'Discussion note — 10:30', source_page: null, source_slide: null, excerpt: 'Normalization reduces duplicate values.' } },
      { type: 'completed' },
    ].map(event => JSON.stringify({ ...event, request_id: question!.request_id })).join('\n') + '\n' })
  })
  await page.goto('/e2e/harness/index.html?socket=discussion')
  await page.getByLabel('Discussion to ask about').selectOption('10')
  const input = page.getByLabel('Ask about this session')
  await input.fill('What did I miss?')
  await input.press('Enter')
  await expect(page.getByText('The discussion covered normalization.', { exact: false })).toBeVisible()
  expect(question!.source).toBe('discussion')
  expect(question!.discussion_since).toBe('2026-11-01T10:20:00.000Z')
  expect(question!.discussion_until).toBe('2026-11-01T10:30:00.000Z')
  await page.getByRole('link', { name: 'Read full discussion note' }).click()
  await expect(page.locator(`#discussion-${noteId}`)).toBeVisible()
  await expect(page.getByText(initial.text, { exact: true })).toBeVisible()
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
})

test('discussion loading errors recover without fabricating a chat source', async ({ page }) => {
  let failed = true
  await page.route('**/api/v1/sessions/discussion-session/discussion', route => failed
    ? route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Minutes unavailable' } } })
    : route.fulfill({ json: { notes: [], latest_recorded_at: null, session_status: 'active' } }))
  await page.goto('/e2e/harness/index.html?socket=discussion')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Ask about this session')).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('No discussion notes have been published.', { exact: false })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('retrying a failed publication reuses its identifier', async ({ page }) => {
  const identifiers: string[] = []
  let saved: typeof initial | undefined
  await page.route('**/api/v1/sessions/discussion-session/discussion**', route => {
    if (route.request().url().endsWith('/automatic-transcripts')) return route.fulfill({ json: automaticOff })
    if (route.request().url().endsWith('/transcripts')) return route.fulfill({ json: { enabled: false, items: [], message: 'Import disabled.' } })
    if (route.request().method() === 'PUT') {
      identifiers.push(route.request().url().split('/').at(-1)!)
      if (identifiers.length === 1) return route.fulfill({ status: 503, json: { error: { message: 'Please retry publication.' } } })
      saved = { ...initial, ...route.request().postDataJSON(), note_id: identifiers[1] }
      return route.fulfill({ json: saved })
    }
    return route.fulfill({ json: { notes: saved ? [saved] : [], latest_recorded_at: saved?.occurred_at ?? null, session_status: 'active' } })
  })
  await page.goto('/e2e/harness/index.html?socket=discussion&publisher')
  await page.getByLabel('Minutes to share with the course').fill(initial.text)
  await page.getByRole('checkbox', { name: 'I reviewed these minutes', exact: false }).check()
  await page.getByRole('button', { name: 'Publish note' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Minutes to share with the course')).toHaveValue(initial.text)
  await page.getByRole('button', { name: 'Publish note' }).click()
  await expect(page.getByText('Read session record (1)')).toBeVisible()
  expect(identifiers).toHaveLength(2)
  expect(identifiers[0]).toBe(identifiers[1])
})

test('transcript minutes require notice confirmation and individual publishing review', async ({ page }) => {
  const notes: typeof initial[] = []
  let draftRequests = 0
  let publication: Record<string, unknown> | undefined
  await page.route('**/api/v1/sessions/discussion-session/discussion**', route => {
    const request = route.request()
    if (request.url().endsWith('/automatic-transcripts')) return route.fulfill({ json: automaticOff })
    if (request.url().endsWith('/transcripts')) return route.fulfill({ json: { enabled: true, items: [{ id: 't1', created_at: noteTime }], message: null } })
    if (request.url().endsWith('/transcript-draft')) {
      draftRequests++
      expect(request.postDataJSON()).toEqual({ transcript_id: 't1', participant_notice_confirmed: true })
      return route.fulfill({ json: { transcript_id: 't1', warning: 'Review before publishing.', notes: [{ ...initial, source_excerpt: 'An exact source quote for the lecturer to verify.', source_offset_seconds: 65 }] } })
    }
    if (request.method() === 'PUT') {
      publication = request.postDataJSON()
      notes.push(initial)
      return route.fulfill({ json: initial })
    }
    return route.fulfill({ json: { notes, latest_recorded_at: notes.length ? noteTime : null, session_status: 'ended' } })
  })
  await page.goto('/e2e/harness/index.html?socket=discussion&publisher')
  const generate = page.getByRole('button', { name: 'Generate draft minutes' })
  await expect(generate).toBeDisabled()
  expect(draftRequests).toBe(0)
  await page.getByRole('checkbox', { name: 'I confirm participants were informed', exact: false }).check()
  await generate.click()
  await expect(page.getByText('Review before publishing.', { exact: false })).toBeVisible()
  expect(notes).toHaveLength(0)
  await page.getByText('Check transcript evidence (offset 1:05)').click()
  await expect(page.getByText('An exact source quote for the lecturer to verify.')).toBeVisible()
  await page.getByRole('button', { name: 'Review in publishing form' }).click()
  await expect(page.getByLabel('Minutes to share with the course')).toHaveValue(initial.text)
  await expect(page.getByLabel('Minutes to share with the course')).toBeFocused()
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
  await expect(page.getByRole('button', { name: 'Publish note' })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'I reviewed these minutes', exact: false }).check()
  await page.getByRole('button', { name: 'Publish note' }).click()
  await expect(page.getByRole('button', { name: 'Already published', exact: false })).toBeDisabled()
  expect(publication).toEqual({ text: initial.text, occurred_at: new Date(noteTime).toISOString(), shareable_confirmed: true })
  await page.reload()
  await expect(page.getByRole('button', { name: 'Review in publishing form' })).toHaveCount(0)
})

test('a live recent-discussion window advances on every new question', async ({ page }) => {
  const bodies: { discussion_since: string; discussion_until: string }[] = []
  await page.route('**/api/v1/sessions/discussion-session/discussion', route => route.fulfill({ json: { notes: [initial], latest_recorded_at: noteTime, session_status: 'active' } }))
  await page.route('**/api/v1/sessions/discussion-session/chat', route => {
    const body = route.request().postDataJSON()
    bodies.push(body)
    return route.fulfill({ contentType: 'application/x-ndjson', body: [
      { type: 'accepted', request_id: body.request_id },
      { type: 'delta', request_id: body.request_id, text: 'Check the current source.' },
      { type: 'completed', request_id: body.request_id },
    ].map(value => JSON.stringify(value)).join('\n') + '\n' })
  })
  await page.clock.setSystemTime(new Date('2026-11-01T10:30:00Z'))
  await page.goto('/e2e/harness/index.html?socket=discussion')
  await page.getByLabel('Discussion to ask about').selectOption('10')
  await page.getByLabel('Ask about this session').fill('What did I miss?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Ask', exact: true })).toBeVisible()
  expect(bodies[0].discussion_since).toMatch(/^2026-11-01T10:20:/)
  expect(Date.parse(bodies[0].discussion_until) - Date.parse(bodies[0].discussion_since)).toBe(600000)
  await page.clock.setSystemTime(new Date('2026-11-01T10:35:00Z'))
  await page.getByLabel('Ask about this session').fill('What was just said?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => bodies.length).toBe(2)
  expect(bodies[1].discussion_since).toMatch(/^2026-11-01T10:25:/)
  expect(Date.parse(bodies[1].discussion_until) - Date.parse(bodies[1].discussion_since)).toBe(600000)
})

test('automatic transcript fetching requires notice and keeps drafts behind review', async ({ page }) => {
  const status = { ...automaticOff, configured: true }
  const writes: Record<string, unknown>[] = []
  let published = false
  await page.route('**/api/v1/sessions/discussion-session/discussion**', route => {
    const request = route.request()
    if (request.url().endsWith('/automatic-transcripts')) {
      if (request.method() === 'PUT') {
        const body = request.postDataJSON()
        expect(body.participant_notice_confirmed).toBe(true)
        status.enabled = body.enabled
        status.subscribed = true
      }
      return route.fulfill({ json: status })
    }
    if (request.url().endsWith('/transcripts')) return route.fulfill({ json: { enabled: false, items: [], message: null } })
    if (request.method() === 'PUT') { writes.push(request.postDataJSON()); published = true; return route.fulfill({ json: initial }) }
    return route.fulfill({ json: { notes: published ? [initial] : [], latest_recorded_at: published ? noteTime : null, session_status: 'ended' } })
  })
  await page.goto('/e2e/harness/index.html?socket=discussion&publisher')
  const panel = page.getByRole('region', { name: 'Automatic Teams transcript fetching' })
  await expect(panel.getByRole('button', { name: 'Enable automatic transcript fetching' })).toBeDisabled()
  await panel.getByRole('checkbox').check()
  await panel.getByRole('button', { name: 'Enable automatic transcript fetching' }).click()
  await expect(panel.getByText('Graph subscription is active.', { exact: false })).toBeVisible()
  const draft = { transcript_id: 't1', notes: [{ ...initial, source_excerpt: initial.text, source_offset_seconds: 0 }], expires_at: '2026-11-10T10:00:00Z', warning: 'Check before publishing.' }
  await page.route('**/automatic-transcripts', route => route.fulfill({ json: { ...status, drafts: [draft] } }))
  await panel.getByRole('button', { name: 'Refresh automatic fetching' }).click()
  await expect(panel.locator('p').filter({ hasText: initial.text })).toBeVisible()
  expect(writes).toHaveLength(0)
  await panel.getByRole('button', { name: 'Review in publishing form' }).click()
  await expect(page.getByLabel('Minutes to share with the course')).toHaveValue(initial.text)
  await expect(page.getByRole('button', { name: 'Publish note', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'I reviewed these minutes', exact: false }).check()
  await page.getByRole('button', { name: 'Publish note', exact: true }).click()
  expect(writes).toHaveLength(1)
  expect(writes[0].shareable_confirmed).toBe(true)
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
})
