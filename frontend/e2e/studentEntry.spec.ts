import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const session = (id = 'new-session') => ({
  id, course_code: 'TEST', title: id === 'new-session' ? 'Newly started class' : 'Another class',
  lecturer_id: 'lecturer', status: 'active',
})

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/**', route => route.fulfill({ json: {
    id: 'student', role: 'student', email: 'student@example.test', full_name: 'Test student',
    consents: ['terms'],
  } }))
  await page.route('**/api/v1/sessions/*/discussion', route => route.fulfill({ json: {
    notes: [], latest_recorded_at: null, session_status: 'active',
  } }))
  await page.routeWebSocket('**/ws/session', socket => socket.onMessage(raw => {
    const message = JSON.parse(String(raw))
    if (message.type !== 'auth') return
    socket.send(JSON.stringify({ type: 'ready', seq: 0, ts: new Date().toISOString(), data: {
      user_id: 'student', session_id: message.data.session_id,
      resumed_from_seq: null, stream_id: 'entry-test',
    } }))
  }))
})

test('a new or unlisted assigned class opens through the membership-checked detail endpoint', async ({ page }) => {
  let reads = 0
  let listReads = 0
  const errors: string[] = []
  page.on('console', message => { if (/same key/.test(message.text())) errors.push(message.text()) })
  await page.route('**/api/v1/sessions', route => { listReads++; return route.fulfill({ json: { items: [], total: 0 } }) })
  await page.route('**/api/v1/sessions/new-session', route => { reads++; return route.fulfill({ json: session() }) })
  await page.goto('/e2e/harness/index.html?socket=student-entry')
  await expect(page.getByRole('heading', { name: 'Newly started class' })).toBeVisible()
  await expect(page.getByText('Waiting for the next checkpoint', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Session unavailable' })).toHaveCount(0)
  expect(reads).toBe(1)
  expect(listReads).toBe(0)
  expect(errors).toEqual([])
})

test('a slow lookup shows loading rather than claiming the class is unassigned', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/sessions/new-session', async route => { await hold; await route.fulfill({ json: session() }) })
  await page.goto('/e2e/harness/index.html?socket=student-entry')
  await expect(page.getByRole('status').filter({ hasText: 'Finding your class' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Session unavailable' })).toHaveCount(0)
  release()
  await expect(page.getByRole('heading', { name: 'Newly started class' })).toBeVisible()
})

for (const failure of ['offline', 'server'] as const) {
  test(`a ${failure} lookup can be retried without changing access rules`, async ({ page }) => {
    let reads = 0
    await page.route('**/api/v1/sessions/new-session', route => {
      reads++
      if (reads > 1) return route.fulfill({ json: session() })
      return failure === 'offline' ? route.abort('failed')
        : route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Try later.' } } })
    })
    await page.goto('/e2e/harness/index.html?socket=student-entry')
    await expect(page.getByRole('heading', { name: 'Could not check this session' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Session unavailable' })).toHaveCount(0)
    const retry = page.getByRole('button', { name: 'Try again' })
    await retry.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: 'Newly started class' })).toBeVisible()
    expect(reads).toBe(2)
  })
}

for (const code of [403, 404]) {
  test(`a ${code} lookup never opens the live socket or exposes a class`, async ({ page }) => {
    let sockets = 0
    let reads = 0
    await page.routeWebSocket('**/ws/session', () => { sockets++ })
    await page.route('**/api/v1/sessions/new-session', route => {
      reads++; return route.fulfill({ status: code, json: { error: { code: 'NOT_FOUND', message: 'Unavailable.' } } })
    })
    await page.goto('/e2e/harness/index.html?socket=student-entry')
    await expect(page.getByRole('heading', { name: 'Session unavailable' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Return to sessions' })).toHaveAttribute('href', '/student')
    await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0)
    expect(reads).toBe(1)
    expect(sockets).toBe(0)
  })
}

test('navigation aborts an old lookup and cannot replace the next class with a late result', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/sessions/new-session', async route => {
    await hold
    await route.fulfill({ json: session() }).catch(() => {})
  })
  await page.route('**/api/v1/sessions/other-session', route => route.fulfill({ json: session('other-session') }))
  await page.goto('/e2e/harness/index.html?socket=student-entry')
  await expect(page.getByRole('status').filter({ hasText: 'Finding your class' })).toBeVisible()
  await page.getByRole('link', { name: 'Open another class' }).click()
  await expect(page.getByRole('heading', { name: 'Another class' })).toBeVisible()
  release()
  await expect(page.getByRole('heading', { name: 'Newly started class' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Another class' })).toBeVisible()
})

test('lookup failure remains usable with keyboard at narrow width', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route('**/api/v1/sessions/new-session', route => route.fulfill({ status: 503, json: {} }))
  await page.goto('/e2e/harness/index.html?socket=student-entry')
  await expect(page.getByRole('heading', { name: 'Could not check this session' })).toBeVisible()
  const results = await new AxeBuilder({ page }).include('section').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(results.violations).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('checkpoint countdown announces milestones instead of every visible second', async ({ page }) => {
  const start = new Date('2026-11-09T10:00:00Z')
  await page.clock.install({ time: start })
  let send!: (event: object) => void
  await page.routeWebSocket('**/ws/session', socket => {
    send = event => socket.send(JSON.stringify(event))
    socket.onMessage(raw => {
      if (JSON.parse(String(raw)).type === 'auth') send({
        type: 'ready', seq: 0, ts: start.toISOString(),
        data: { user_id: 'student', session_id: 'new-session', resumed_from_seq: null, stream_id: 'timer-test' },
      })
    })
  })
  await page.route('**/api/v1/sessions/new-session', route => route.fulfill({ json: session() }))
  await page.goto('/e2e/harness/index.html?socket=student-entry')
  await expect(page.getByText('Waiting for the next checkpoint', { exact: true })).toBeVisible()
  const sentAt = await page.evaluate(() => Date.now())
  send({ type: 'question.delivered', seq: 1, ts: start.toISOString(), data: {
    question_id: 'timer-question', prompt: 'Checkpoint timing?', options: ['First', 'Second'],
    closes_at: new Date(sentAt + 12_000).toISOString(), window_seconds: 12, source_slide: 1,
  } })
  const timer = page.getByRole('timer')
  await expect(timer).toHaveText('')
  await page.clock.runFor(2_000)
  await expect(timer).toHaveText('10 seconds left.')
  await page.clock.runFor(1_000)
  await expect(timer).toHaveText('10 seconds left.')
  await page.clock.runFor(4_000)
  await expect(timer).toHaveText('5 seconds left.')
})

test('the compact Teams panel exposes both policies without hiding the class', async ({ page }) => {
  await page.goto('/e2e/harness/index.html?socket=student-panel&compact=1')
  await expect(page.getByRole('link', { name: 'Privacy notice', exact: true })).toHaveAttribute('href', '/privacy')
  await expect(page.getByRole('link', { name: 'Terms of use', exact: true })).toHaveAttribute('href', '/terms')
  await expect(page.getByText('Waiting for the next checkpoint', { exact: true })).toBeVisible()
})
