import { expect, test, type Page } from '@playwright/test'

async function optIn(page: Page, sensor: 'camera' | 'microphone') {
  await page.getByLabel(`I opt in to ${sensor} indicators`).check()
  await page.getByRole('button', { name: 'Save monitoring and selected device opt-in' }).click()
  await expect(page.getByRole('button', { name: 'Enable selected' })).toBeEnabled()
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('clip_access_token', 'test-only')
    const state = { requests: 0, tracks: [] as MediaStreamTrack[], scroll: [] as unknown[], summaries: [] as unknown[] }
    Object.assign(window, { probe: state })
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {
      state.requests++
      const stream = await original(constraints)
      state.tracks.push(...stream.getTracks())
      return stream
    }
    Element.prototype.scrollIntoView = function(options) { state.scroll.push(options) }
    window.addEventListener('test-summary', event => state.summaries.push((event as CustomEvent).detail))
  })
  await page.route('**/api/v1/auth/**', route => route.fulfill({ json: {
    id: 'student', email: 'student@example.test', full_name: 'Test student', role: 'student',
    consents: ['engagement_monitoring', 'camera', 'microphone'],
  } }))
  await page.goto('/e2e/harness/index.html')
})

test('devices remain off until saved opt-in and explicit enable; denial is recoverable', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Enable selected' })).toBeDisabled()
  await optIn(page, 'camera')
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') }
  })
  await page.getByRole('button', { name: 'Enable selected' }).click()
  await expect(page.getByText('Camera: unavailable. Microphone: off.')).toBeVisible()
  await expect(page.getByRole('status')).toHaveText('Local sensing off')
  await expect(page.getByLabel('Ask about this session')).toBeEnabled()
})

test('microphone denial and consent-save failure never strand the interface', async ({ page }) => {
  await page.route('**/api/v1/auth/consent', route => route.fulfill({ status: 503, json: {} }))
  await page.getByLabel('I opt in to microphone indicators').check()
  await page.getByRole('button', { name: 'Save monitoring and selected device opt-in' }).click()
  await expect(page.getByRole('alert')).toContainText('No device was started')
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  await page.unroute('**/api/v1/auth/consent')
  await page.getByRole('button', { name: 'Save monitoring and selected device opt-in' }).click()
  await expect(page.getByRole('button', { name: 'Enable selected' })).toBeEnabled()
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') }
  })
  await page.getByRole('button', { name: 'Enable selected' }).click()
  await expect(page.getByText('Camera: off. Microphone: unavailable.')).toBeVisible()
})

test('cancel a pending permission request and release a late stream', async ({ page }) => {
  await page.evaluate(() => {
    const original = navigator.mediaDevices.getUserMedia
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await original(constraints)
      await new Promise<void>(resolve => { Object.assign(window, { releasePermission: resolve }) })
      return stream
    }
  })
  await optIn(page, 'camera')
  await page.getByRole('button', { name: 'Enable selected' }).click()
  await expect.poll(() => page.evaluate(() => typeof (window as any).releasePermission)).toBe('function')
  await page.getByRole('button', { name: 'Disable all now' }).click()
  await page.evaluate(() => (window as any).releasePermission())
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState))).toEqual(['ended'])
  await expect(page.getByRole('status')).toHaveText('Local sensing off')
})

for (const sensor of ['camera', 'microphone'] as const) {
  test(`${sensor}: real local model startup, derived summaries and shutdown under CPU throttling`, async ({ page, context }, info) => {
    const external: string[] = []
    page.on('request', request => {
      if (!request.url().startsWith('http://127.0.0.1:4174/') && !request.url().startsWith('blob:')) external.push(request.url())
    })
    const cdp = await context.newCDPSession(page)
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
    await optIn(page, sensor)
    const start = Date.now()
    await page.getByRole('button', { name: 'Enable selected' }).click()
    await expect(page.getByRole('button', { name: `Stop ${sensor}`, exact: true })).toBeVisible({ timeout: 60_000 })
    const startupMs = Date.now() - start
    await expect.poll(() => page.evaluate(() => (window as any).probe.summaries.length), { timeout: 15_000 }).toBeGreaterThan(0)
    const summaries = await page.evaluate(() => (window as any).probe.summaries)
    for (const summary of summaries) {
      expect(Object.keys(summary).sort()).toEqual(['face_present', 'gaze_on_screen_ratio', 'speaking', 'window_seconds'])
      expect(summary.window_seconds).toBeGreaterThan(0)
      expect(summary.window_seconds).toBeLessThanOrEqual(3600)
    }
    expect(external).toEqual([])
    await info.attach(`${sensor}-synthetic-performance.json`, { body: JSON.stringify({ startupMs, cpuThrottle: 4, summaries, externalRequests: external }), contentType: 'application/json' })
    await page.getByRole('button', { name: 'Disable all now' }).click()
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))).toBe(true)
    await expect(page.getByRole('status')).toHaveText('Local sensing off')
  })
}

for (const action of ['Toggle session connection', 'Toggle sensor mount', 'Reject consent', 'pagehide', 'hidden']) {
  test(`camera releases tracks on ${action}`, async ({ page }) => {
    await optIn(page, 'camera')
    await page.getByRole('button', { name: 'Enable selected' }).click()
    await expect(page.getByRole('button', { name: 'Stop camera', exact: true })).toBeVisible({ timeout: 60_000 })
    if (action === 'pagehide') await page.evaluate(() => window.dispatchEvent(new Event('pagehide')))
    else if (action === 'hidden') await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    else await page.getByRole('button', { name: action, exact: true }).click()
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))).toBe(true)
  })
}

test('keyboard, IME composition, source rendering and reduced-motion scrolling', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let requests = 0
  await page.route('**/sessions/phase8/chat', async route => {
    requests++
    const { request_id } = route.request().postDataJSON()
    await route.fulfill({ contentType: 'application/x-ndjson', body: [
      { type: 'accepted' }, { type: 'delta', text: 'What principle applies here?' },
      { type: 'citation', citation: { id: 'c1', material_title: 'Lecture notes', source_page: 2, source_slide: null, excerpt: 'A verified source.' } },
      { type: 'completed' },
    ].map(event => JSON.stringify({ ...event, request_id })).join('\n') + '\n' })
  })
  const input = page.getByLabel('Ask about this session')
  await input.focus()
  await input.fill('Help me reason')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  expect(requests).toBe(0)
  await input.press('Shift+Enter')
  expect(requests).toBe(0)
  await input.press('Tab')
  await expect(page.getByRole('button', { name: 'Ask', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByText('What principle applies here?')).toBeVisible()
  await expect(page.getByText('Lecture notes · Page 2')).toBeVisible()
  expect(await page.evaluate(() => (window as any).probe.scroll.at(-1).behavior)).toBe('instant')
})

test('keyboard can cancel a live incremental response and keep partial text', async ({ page }) => {
  const input = page.getByLabel('Ask about this session')
  await input.fill('Give me a hint')
  await input.press('Enter')
  await expect(page.getByText('Start with the first principle.')).toBeVisible()
  const stop = page.getByRole('button', { name: 'Stop response', exact: true })
  await stop.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Response stopped', { exact: true })).toBeVisible()
  await expect(page.getByText('Start with the first principle.')).toBeVisible()
  await expect(input).toBeEnabled()
})

test('keyboard-only opt-in and disable controls are operable', async ({ page }) => {
  const checkbox = page.getByLabel('I opt in to camera indicators')
  await checkbox.focus()
  await page.keyboard.press('Space')
  await expect(checkbox).toBeChecked()
  await page.keyboard.press('Tab') // microphone checkbox
  await page.keyboard.press('Tab') // save
  await expect(page.getByRole('button', { name: 'Save monitoring and selected device opt-in' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Enable selected' })).toBeEnabled()
  await page.getByRole('button', { name: 'Save monitoring and selected device opt-in' }).focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Enable selected' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Stop camera', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Disable all now' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status')).toHaveText('Local sensing off')
})

test('missing self-hosted face model stops capture and explains unavailability', async ({ page }) => {
  await page.route('**/attention/**/face_landmarker.task', route => route.abort())
  await page.route('**/attention/face_landmarker.task', route => route.abort())
  await optIn(page, 'camera')
  await page.getByRole('button', { name: 'Enable selected' }).click()
  await expect(page.getByText('Camera: unavailable. Microphone: off.')).toBeVisible({ timeout: 40_000 })
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))).toBe(true)
})
