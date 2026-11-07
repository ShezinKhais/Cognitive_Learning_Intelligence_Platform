import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const noteId = '27f347a5-1595-4448-9244-b6849b51e936'
const noteTime = '2026-11-01T10:30:00Z'
const initial = { note_id: noteId, text: 'Normalization reduces duplicate database values.', occurred_at: noteTime, updated_at: noteTime }

test('lecturer confirms, publishes, corrects and removes course minutes', async ({ page }) => {
  let notes: typeof initial[] = []
  const writes: Record<string, unknown>[] = []
  await page.route('**/api/v1/sessions/discussion-session/discussion**', async route => {
    const request = route.request()
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
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Publish note' }).click()
  await page.getByText('Read published minutes (1)').click()
  await expect(page.getByText(initial.text, { exact: true })).toBeVisible()
  expect(writes[0].shareable_confirmed).toBe(true)
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await page.getByLabel('Minutes to share with the course').fill('Corrected teaching point.')
  await page.getByRole('checkbox').check()
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
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Publish note' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Minutes to share with the course')).toHaveValue(initial.text)
  await page.getByRole('button', { name: 'Publish note' }).click()
  await expect(page.getByText('Read published minutes (1)')).toBeVisible()
  expect(identifiers).toHaveLength(2)
  expect(identifiers[0]).toBe(identifiers[1])
})
