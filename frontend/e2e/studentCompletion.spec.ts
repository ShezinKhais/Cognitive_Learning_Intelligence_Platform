import { expect, test, type WebSocketRoute } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// The actual exported student panel, with synthetic auth/socket transport.
// Exercise terminal state independently of retained checkpoint feedback.
for (const status of ['ended', 'cancelled'] as const) {
  for (const checkpoint of ['none', 'answering', 'submitted', 'missed', 'submitting', 'unconfirmed', 'rejected'] as const) {
    test(`${status} student session with ${checkpoint} checkpoint shows honest completion`, async ({ page }) => {
      if (checkpoint === 'unconfirmed') await page.clock.install()
      let connection: WebSocketRoute | undefined
      let sequence = 0
      function emit(type: string, data: object) {
        connection!.send(JSON.stringify({ type, data, seq: ++sequence, ts: new Date().toISOString() }))
      }
      function sessionState(phase: string) {
        emit('session.state', { session_id: 'completion-session', status: phase, paused: false,
          participant_count: 1, active_question_id: null, questions_delivered: checkpoint === 'none' ? 0 : 1 })
      }
      await page.route('**/api/v1/auth/**', route => route.fulfill({ json: {
        id: 'student', role: 'student', email: 'student@example.test', full_name: 'Synthetic student',
        consents: ['terms'],
      } }))
      await page.routeWebSocket('**/ws/session', ws => {
        connection = ws
        ws.onMessage(message => {
          const event = JSON.parse(String(message))
          if (event.type === 'auth') {
            ws.send(JSON.stringify({ type: 'ready', seq: 0, ts: new Date().toISOString(),
              data: { user_id: 'student', session_id: 'completion-session',
                resumed_from_seq: null, stream_id: 'completion-regression' } }))
            sessionState('active')
          }
          if (event.type === 'answer.submit' && checkpoint === 'submitted') {
            emit('answer.receipt', { question_id: 'completion-question', accepted: true,
              received_at: new Date().toISOString(), reason: null })
            emit('feedback.result', { question_id: 'completion-question', correct: false,
              explanation: 'Synthetic feedback is preserved.', source_slide: 3 })
          } else if (event.type === 'answer.submit' && checkpoint === 'rejected') {
            emit('answer.receipt', { question_id: 'completion-question', accepted: false,
              received_at: new Date().toISOString(), reason: 'Synthetic rejection.' })
          }
        })
      })
      // Exercise the same completion shortcut in the compact Teams panel too.
      await page.goto(`/e2e/harness/index.html?socket=student-panel${checkpoint === 'none' ? '&compact=1' : ''}`)
      await expect(page.getByText('Waiting for the next checkpoint', { exact: true })).toBeVisible()
      if (checkpoint !== 'none') {
        emit('question.delivered', { question_id: 'completion-question', prompt: 'Synthetic checkpoint?',
          options: ['First', 'Second'], closes_at: new Date(Date.now() + 60_000).toISOString(),
          window_seconds: 60, source_slide: 3 })
        await expect(page.getByRole('heading', { name: 'Synthetic checkpoint?' })).toBeVisible()
        if (['submitted', 'submitting', 'unconfirmed', 'rejected'].includes(checkpoint)) {
          const option = page.getByRole('radio', { name: /First/ })
          await option.focus()
          await option.press('Space')
          await page.getByRole('button', { name: 'Submit answer' }).click()
          if (checkpoint === 'submitted') {
            await expect(page.getByText('Synthetic feedback is preserved.')).toBeVisible()
          } else if (checkpoint === 'rejected') {
            await expect(page.getByText('Synthetic rejection.')).toBeVisible()
          } else {
            await expect(page.getByText('Saving your answer…')).toBeVisible()
            if (checkpoint === 'unconfirmed') {
              emit('question.closed', { question_id: 'completion-question', reason: 'window_elapsed',
                respondents: 0, eligible: 1 })
              await page.clock.runFor(100)
              await page.clock.fastForward(11_000)
              await expect(page.getByText('Answer confirmation unavailable')).toBeVisible()
            }
          }
        } else if (checkpoint === 'missed') {
          emit('question.closed', { question_id: 'completion-question', reason: 'window_elapsed',
            respondents: 0, eligible: 1 })
          await expect(page.getByText('Response window closed', { exact: true })).toBeVisible()
        }
      }
      sessionState(status)
      await expect(page.getByRole('heading', {
        name: status === 'ended' ? 'This session has ended' : 'This session was cancelled',
      })).toBeVisible()
      await expect(page.getByText(/The lecturer’s next question will appear/)).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Submit answer' })).toHaveCount(0)
      await expect(page.getByRole('radio')).toHaveCount(0)
      await expect(page.getByText('Saving your answer…')).toHaveCount(0)
      await expect(page.getByText('You can continue participating in the session.', { exact: false })).toHaveCount(0)
      const review = page.getByRole('link', { name: 'See how you did' })
      if (status === 'ended') {
        await expect(review).toHaveAttribute('href', '/student/session/completion-session/summary')
      } else {
        await expect(review).toHaveCount(0)
        await expect(page.getByText('There is no post-session review for a cancelled session.')).toBeVisible()
      }
      if (checkpoint === 'submitted') {
        await expect(page.getByText('Synthetic feedback is preserved.')).toBeVisible()
      }
      if (checkpoint === 'missed') {
        await expect(page.getByText('Response window closed', { exact: true })).toBeVisible()
      }
      if (checkpoint === 'submitting' || checkpoint === 'unconfirmed') {
        await expect(page.getByText('Answer confirmation unavailable')).toBeVisible()
        // A delayed receipt/feedback must update the outcome without reviving the form.
        emit('answer.receipt', { question_id: 'completion-question', accepted: true,
          received_at: new Date().toISOString(), reason: null })
        emit('feedback.result', { question_id: 'completion-question', correct: false,
          explanation: 'Late feedback is preserved.', source_slide: 3 })
        await expect(page.getByText('Late feedback is preserved.')).toBeVisible()
        await expect(page.getByRole('radio')).toHaveCount(0)
      }
    })
  }
}


test.describe('Post-session revision and catch-up', () => {
const session = { id: 'review-session', title: 'Review synthetic lecture', course_code: 'SYNTHETIC', ended_at: '2026-11-01T10:00:00Z' }
const answer = { id: 'own-response', question: 'Which planet is largest?', topic: 'Planets', answer: 'Mars', is_correct: false, label: null, confidence: null, submitted_at: session.ended_at, correct_answer: 'Jupiter', key_points: [] }
const missed = { id: 'own-miss', question: 'What does normalization reduce?', topic: 'Databases', correct_answer: 'Duplicate values', key_points: ['Reduce duplication'] }
const source = { items: [{ chunk_id: 'source', material_title: 'Verified lecture.pdf', source_page: 3, text: 'Normalization reduces duplicate values.', match: 'excerpt' }], has_more: false }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/sessions/review-session/discussion', route => route.fulfill({ json: { notes: [{ note_id: 'published-note', occurred_at: session.ended_at, updated_at: session.ended_at, text: 'Published synthetic teaching point.' }], latest_recorded_at: session.ended_at, session_status: 'ended' } }))
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
  await page.goto('/e2e/review/index.html')
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
  await page.goto('/e2e/review/index.html')
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
  await page.goto('/e2e/review/index.html')
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
  expect(requests[1].history ?? []).toEqual([])
  await page.reload()
  await expect(page.getByText('Which feature would you compare?', { exact: true })).toHaveCount(0)
})

test('denied review never opens material or discussion tutoring', async ({ page }) => {
  await page.route('**/api/v1/student-reviews/review-session?*', route => route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message: 'Unavailable' } } }))
  await page.goto('/e2e/review/index.html')
  await expect(page.getByRole('heading', { name: 'This review was not found' })).toBeVisible()
  await expect(page.getByLabel('Ask about this session')).toHaveCount(0)
})

})
