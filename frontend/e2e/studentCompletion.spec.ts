import { expect, test, type WebSocketRoute } from '@playwright/test'

// The actual exported student panel, with synthetic auth/socket transport.
// Exercise terminal state independently of retained checkpoint feedback.
for (const status of ['ended', 'cancelled'] as const) {
  for (const checkpoint of ['none', 'submitted', 'missed'] as const) {
    test(`${status} student session with ${checkpoint} checkpoint shows honest completion`, async ({ page }) => {
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
          if (event.type === 'answer.submit') {
            emit('answer.receipt', { question_id: 'completion-question', accepted: true,
              received_at: new Date().toISOString(), reason: null })
            emit('feedback.result', { question_id: 'completion-question', correct: false,
              explanation: 'Synthetic feedback is preserved.', source_slide: 3 })
          }
        })
      })
      await page.goto('/e2e/harness/index.html?socket=student-panel')
      await expect(page.getByText('Waiting for the next checkpoint', { exact: true })).toBeVisible()
      if (checkpoint !== 'none') {
        emit('question.delivered', { question_id: 'completion-question', prompt: 'Synthetic checkpoint?',
          options: ['First', 'Second'], closes_at: new Date(Date.now() + 60_000).toISOString(),
          window_seconds: 60, source_slide: 3 })
        await expect(page.getByRole('heading', { name: 'Synthetic checkpoint?' })).toBeVisible()
        if (checkpoint === 'submitted') {
          const option = page.getByRole('radio', { name: /First/ })
          await option.focus()
          await option.press('Space')
          await page.getByRole('button', { name: 'Submit answer' }).click()
          await expect(page.getByText('Synthetic feedback is preserved.')).toBeVisible()
        } else {
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
    })
  }
}
