import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const session = { id: 'review-session', title: 'Review synthetic lecture', course_code: 'SYNTHETIC', ended_at: '2026-11-01T10:00:00Z' }
const answer = { id: 'own-response', question: 'Which planet is largest?', topic: 'Planets', answer: 'Mars', is_correct: false, label: null, confidence: null, submitted_at: session.ended_at, correct_answer: 'Jupiter', key_points: [] }
const missed = { id: 'own-miss', question: 'What does normalization reduce?', topic: 'Databases', correct_answer: 'Duplicate values', key_points: ['Reduce duplication'] }
const source = { items: [{ chunk_id: 'source', material_title: 'Verified lecture.pdf', source_page: 3, text: 'Normalization reduces duplicate values.', match: 'excerpt' }], has_more: false }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/sessions/review-session/discussion', route => route.fulfill({ json: { notes: [], latest_recorded_at: null, session_status: 'ended' } }))
  await page.route('**/api/v1/student-reviews/review-session**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/sources')) return route.fulfill({ json: source })
    if (url.pathname.endsWith('/missed')) return route.fulfill({ json: { items: [missed], total: 1, offset: 0, limit: 20 } })
    return route.fulfill({ json: { session, questions_attempted: 1, questions_missed: 1, answers: [answer], total: 1, offset: 0, limit: 20,
      engagement: { status: 'unavailable', score: null, explanation: 'Missing readings are not zero.' },
    } })
  })
})

test('review shows wrong and unanswered separately with reference answers and scoped sources', async ({ page }) => {
  const sourcePaths: string[] = []
  page.on('request', request => { if (request.url().endsWith('/sources')) sourcePaths.push(new URL(request.url()).pathname) })
  await page.goto('/e2e/harness/index.html?socket=review')
  await expect(page.getByText('Jupiter', { exact: true })).toBeVisible()
  await expect(page.getByText('Duplicate values', { exact: true })).toBeVisible()
  await expect(page.getByText('Unanswered', { exact: true })).toBeVisible()
  await expect(page.getByText('Not recorded for this session')).toBeVisible()
  expect(sourcePaths).toEqual([])
  await page.getByRole('button', { name: 'Show where this came from' }).click()
  await page.getByText('Show source for this unanswered checkpoint', { exact: true }).click()
  await expect(page.getByText(source.items[0].text, { exact: true })).toHaveCount(2)
  expect(sourcePaths.sort()).toEqual([
    '/api/v1/student-reviews/review-session/missed/own-miss/sources',
    '/api/v1/student-reviews/review-session/responses/own-response/sources',
  ])
  const accessibility = await new AxeBuilder({ page }).disableRules(['landmark-one-main', 'region']).analyze()
  expect(accessibility.violations).toEqual([])
  await page.reload()
  await expect(page.getByText('Jupiter', { exact: true })).toBeVisible()
})

test('missed checkpoints paginate independently when there are no submitted answers', async ({ page }) => {
  await page.route('**/api/v1/student-reviews/review-session?*', route => route.fulfill({ json: {
    session, questions_attempted: 0, questions_missed: 21, answers: [], total: 0, limit: 20, offset: 0,
    engagement: { status: 'unavailable', score: null, explanation: 'No verified record.' },
  } }))
  await page.route('**/api/v1/student-reviews/review-session/missed?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'))
    return route.fulfill({ json: { items: offset ? [{ ...missed, id: 'last', question: 'Final missed checkpoint' }] : [missed], total: 21, offset, limit: 20 } })
  })
  await page.goto('/e2e/harness/index.html?socket=review')
  await expect(page.getByRole('heading', { name: 'No answers from you in this session' })).toBeVisible()
  const pager = page.getByRole('navigation', { name: 'More unanswered checkpoints' })
  await pager.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('heading', { name: 'Final missed checkpoint' })).toBeVisible()
  await expect(pager).toContainText('21 to 21 of 21')
})

test('post-session material tutoring and discussion catch-up keep separate in-memory conversations', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/v1/sessions/review-session/chat', route => {
    const body = route.request().postDataJSON()
    requests.push(body)
    return route.fulfill({ contentType: 'application/x-ndjson', body: [
      { type: 'accepted' }, { type: 'delta', text: body.source === 'discussion' ? 'Published notes help you catch up.' : 'Which feature would you compare?' }, { type: 'completed' },
    ].map(event => JSON.stringify({ ...event, request_id: body.request_id })).join('\n') + '\n' })
  })
  await page.goto('/e2e/harness/index.html?socket=review')
  const material = page.getByRole('region', { name: 'Socratic learning assistant' })
  await material.getByLabel('Ask about this session').fill('Help me understand the material')
  await material.getByLabel('Ask about this session').press('Enter')
  await expect(material.getByText('Which feature would you compare?', { exact: true })).toBeVisible()
  const discussion = page.getByRole('region', { name: 'Ask about the discussion' })
  await discussion.getByLabel('Ask about this session').fill('What was discussed?')
  await discussion.getByLabel('Ask about this session').press('Enter')
  await expect(discussion.getByText('Published notes help you catch up.', { exact: true })).toBeVisible()
  expect(requests[0].source).not.toBe('discussion')
  expect(requests[1].source).toBe('discussion')
  expect(requests[1].history).toEqual([])
  await page.reload()
  await expect(page.getByText('Which feature would you compare?', { exact: true })).toHaveCount(0)
})

test('denied review never opens material or discussion tutoring', async ({ page }) => {
  await page.route('**/api/v1/student-reviews/review-session?*', route => route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message: 'Unavailable' } } }))
  await page.goto('/e2e/harness/index.html?socket=review')
  await expect(page.getByRole('heading', { name: 'This review was not found' })).toBeVisible()
  await expect(page.getByLabel('Ask about this session')).toHaveCount(0)
})
