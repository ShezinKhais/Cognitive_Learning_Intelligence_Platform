import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// The indicators panel is one line until it is opened.
async function showIndicators(page: Page) {
  const show = page.getByRole('button', { name: 'Show options' })
  if (await show.isVisible()) await show.click()
}

async function optIn(page: Page, sensor: 'camera' | 'microphone') {
  await showIndicators(page)
  await page.getByLabel(`I opt in to ${sensor} indicators`).check()
  await page.getByRole('button', { name: 'Save my choice' }).click()
  await expect(page.getByRole('button', { name: 'Turn on' })).toBeEnabled()
}

const granted = new Set<string>()

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
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
  // Consents start empty and change as the page records them, as on the
  // server, so the panel's remembered choices can be tested.
  granted.clear()
  await page.route('**/api/v1/me/consideration/policy', route => route.fulfill({ json: { camera_allowed: true } }))
  await page.route('**/api/v1/auth/**', route => {
    const request = route.request()
    if (request.method() === 'POST' && request.url().endsWith('/auth/consent')) {
      const body = request.postDataJSON() as { consent_type: string; granted: boolean }
      if (body.granted) granted.add(body.consent_type)
      else granted.delete(body.consent_type)
      return route.fulfill({ json: { consent_type: body.consent_type, granted: body.granted } })
    }
    return route.fulfill({ json: {
      id: 'student', email: 'student@example.test', full_name: 'Test student', role: 'student',
      consents: [...granted],
    } })
  })
  // The token is kept in memory and fetched with the refresh cookie on load.
  // Registered last, so it wins over the route above for this one path.
  await page.route('**/api/v1/auth/refresh', route => route.fulfill({ json: {
    access_token: 'test-only', token_type: 'bearer', expires_in: 3600, role: 'student',
  } }))
  await page.goto('/e2e/harness/index.html')
})

test.describe('Approved camera-off capture policy', () => {
  for (const monitoring of [true, false]) {
    test(`camera-off approval wins over saved device consent (monitoring=${monitoring})`, async ({ page }) => {
      granted.add('camera')
      if (monitoring) granted.add('engagement_monitoring')
      await page.route('**/api/v1/me/consideration/policy', route => route.fulfill({ json: { camera_allowed: false } }))
      await page.reload()
      await expect(page.getByText('Your approved camera-off accommodation is active.', { exact: false })).toBeVisible()
      await page.getByRole('button', { name: 'Show options' }).click()
      await expect(page.getByLabel('I opt in to camera indicators')).toBeDisabled()
      expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
    })
  }

  test('policy refresh shares an in-flight camera start check and skips idle consent', async ({ page }) => {
    await page.clock.install()
    await page.reload()
    await page.getByRole('button', { name: 'Show options' }).waitFor()
    await optIn(page, 'camera')
    let checks = 0
    let releasePolicy!: () => void
    let consentRequests = 0
    let allowConsent = false
    await page.route('**/api/v1/auth/me', route => {
      consentRequests++
      return route.fulfill(allowConsent
        ? { json: { id: 'student', role: 'student', consents: [...granted] } }
        : { status: 503, json: {} })
    })
    await page.route('**/api/v1/me/consideration/policy', async route => {
      checks++
      if (checks === 2) await new Promise<void>(resolve => { releasePolicy = resolve })
      return route.fulfill({ json: { camera_allowed: true } })
    })

    await page.clock.fastForward(5000)
    await expect.poll(() => checks).toBe(1)
    expect(consentRequests).toBe(0)
    await expect(page.getByText('Consent could not be verified.', { exact: false })).toHaveCount(0)
    allowConsent = true
    await page.clock.fastForward(1000)
    await page.getByRole('button', { name: 'Turn on', exact: true }).click()
    await expect.poll(() => Boolean(releasePolicy)).toBe(true)
    // Cross the next poll without reaching the request's own five-second timeout.
    await page.clock.fastForward(4500)
    await expect.poll(() => consentRequests).toBe(1)
    expect(checks).toBe(2)
    releasePolicy()
    await expect.poll(() => page.evaluate(() => (window as any).probe.requests)).toBe(1)
  })

  test('a changed policy cancels pending camera permission and releases a late stream', async ({ page }) => {
    let allowed = true
    await page.route('**/api/v1/me/consideration/policy', route => route.fulfill({ json: { camera_allowed: allowed } }))
    await page.evaluate(() => {
      const original = navigator.mediaDevices.getUserMedia
      navigator.mediaDevices.getUserMedia = async constraints => {
        const stream = await original(constraints)
        await new Promise<void>(resolve => { Object.assign(window, { releasePolicyStream: resolve }) })
        return stream
      }
    })
    await optIn(page, 'camera')
    await page.getByRole('button', { name: 'Turn on', exact: true }).click()
    await expect.poll(() => page.evaluate(() => typeof (window as any).releasePolicyStream)).toBe('function')
    allowed = false
    await expect(page.getByText('Your approved camera-off accommodation is active.', { exact: false })).toBeVisible({ timeout: 12_000 })
    await page.evaluate(() => (window as any).releasePolicyStream())
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((track: MediaStreamTrack) => track.readyState))).toEqual(['ended'])
    await expect(page.getByText('Camera: off. Microphone: off.')).toBeVisible()
    allowed = true
    await expect(page.getByLabel('I opt in to camera indicators')).toBeEnabled({ timeout: 12_000 })
    expect(await page.evaluate(() => (window as any).probe.requests)).toBe(1)
    await expect(page.getByLabel('I opt in to camera indicators')).not.toBeChecked()
  })

  test('policy failure blocks remembered camera consent and recovery never silently restarts', async ({ page }) => {
    let available = false
    granted.add('camera'); granted.add('engagement_monitoring')
    await page.route('**/api/v1/me/consideration/policy', route => route.fulfill({ status: available ? 200 : 503, json: available ? { camera_allowed: true } : {} }))
    await page.reload()
    await page.getByRole('button', { name: 'Show options' }).click()
    await expect(page.getByText('Camera policy could not be verified.', { exact: false })).toBeVisible()
    await expect(page.getByLabel('I opt in to camera indicators')).toBeDisabled()
    expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
    available = true
    await expect(page.getByLabel('I opt in to camera indicators')).toBeEnabled({ timeout: 12_000 })
    expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
    await expect(page.getByLabel('I opt in to camera indicators')).not.toBeChecked()
  })

  for (const action of ['Turn everything off', 'Toggle sensor mount', 'Toggle session connection']) {
    test(`late consent verification cannot start hardware after ${action}`, async ({ page }) => {
      await optIn(page, 'camera')
      let release: (() => void) | undefined
      await page.route('**/api/v1/auth/me', async route => {
        await new Promise<void>(resolve => { release = resolve })
        return route.fulfill({ json: { id: 'student', role: 'student', consents: [...granted] } })
      })
      await page.getByRole('button', { name: 'Turn on', exact: true }).click()
      await expect.poll(() => Boolean(release)).toBe(true)
      await page.getByRole('button', { name: action, exact: true }).click()
      const finished = page.waitForResponse('**/api/v1/auth/me')
      release!()
      await finished
      // Give the already-resolved authorization continuation a turn to run.
      await page.waitForTimeout(150)
      expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
    })
  }

  test('manual start rechecks a newly approved restriction before opening the camera', async ({ page }) => {
    let allowed = true
    await page.route('**/api/v1/me/consideration/policy', route => route.fulfill({ json: { camera_allowed: allowed } }))
    await optIn(page, 'camera')
    allowed = false
    await page.getByRole('button', { name: 'Turn on', exact: true }).click()
    await expect(page.getByText('Your approved camera-off accommodation is active.', { exact: false })).toBeVisible()
    expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  })
})

test('student room selection uses only the existing event and respects live session state', async ({ page }) => {
  let connection: WebSocketRoute | undefined
  let connected = 0
  const selections: unknown[] = []
  await page.routeWebSocket('**/ws/session', ws => {
    connection = ws
    connected++
    ws.onMessage(message => {
      const event = JSON.parse(String(message))
      if (event.type === 'auth') ws.send(JSON.stringify({
        type: 'ready', seq: 0, ts: new Date().toISOString(), data: {
          user_id: 'student', session_id: 'refresh-session',
          resumed_from_seq: null, stream_id: 'room-test',
        },
      }))
      if (event.type === 'room.confirm') selections.push(event.data)
    })
  })
  await page.goto('/e2e/harness/index.html?socket=student')
  const send = page.getByRole('button', { name: 'Send room selection' })
  await expect(send).toBeEnabled()
  await page.getByLabel('Assigned room name').fill('  Room   2  ')
  await send.click()
  await expect.poll(() => selections).toEqual([{ room_label: 'Room 2' }])
  await expect(page.getByRole('status')).toContainText('Room selection sent: Room 2')
  connection!.send(JSON.stringify({ type: 'error', seq: 0, ts: new Date().toISOString(),
    data: { code: 'RATE_LIMITED', detail: 'attention.summary is being sent too often' } }))
  await expect(page.getByRole('status')).toContainText('Room selection sent: Room 2')
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
  connection!.close({ code: 1012, reason: 'service restart' })
  await expect.poll(() => connected).toBe(2)
  await expect(send).toBeEnabled()
  await expect(page.getByLabel('Assigned room name')).toHaveValue('  Room   2  ')
  expect(selections).toEqual([{ room_label: 'Room 2' }]) // Never silently replay a selection.
  connection!.send(JSON.stringify({ type: 'error', seq: 0, ts: new Date().toISOString(),
    data: { code: 'ROOM_LIMIT', detail: 'No more rooms can be added.' } }))
  await expect(page.getByRole('status')).toContainText('may not have been accepted')
  for (const [seq, status, paused] of [[1, 'active', true], [2, 'ended', false]] as const) {
    connection!.send(JSON.stringify({ type: 'session.state', seq, ts: new Date().toISOString(), data: {
      session_id: 'refresh-session', status, paused, participant_count: 1,
      active_question_id: null, questions_delivered: 0,
    } }))
    await expect(send).toBeDisabled()
  }
  expect(selections).toEqual([{ room_label: 'Room 2' }])
})

test('room selection is unavailable without a ready live connection', async ({ page }) => {
  await page.routeWebSocket('**/ws/session', () => {})
  await page.goto('/e2e/harness/index.html?socket=student')
  await expect(page.getByRole('button', { name: 'Send room selection' })).toBeDisabled()
  await expect(page.getByLabel('Assigned room name')).toBeDisabled()
})

for (const socket of ['student', 'lecturer', 'progress']) {
  for (const failure of ['offline', '503'] as const) {
    test(`${socket} socket keeps credentials when refresh is ${failure} and recovers`, async ({ page }) => {
      let refreshes = 0
      const tokens: string[] = []
      await page.route('**/api/v1/auth/refresh', route => {
        refreshes++
        if (refreshes === 1) return failure === 'offline'
          ? route.abort('failed') : route.fulfill({ status: 503, json: {} })
        return route.fulfill({ json: {
          access_token: 'recovered-token', expires_in: 3600, token_type: 'bearer', role: 'student',
        } })
      })
      await page.routeWebSocket('**/ws/session', ws => ws.onMessage(message => {
        const event = JSON.parse(String(message))
        if (event.type !== 'auth') return
        tokens.push(event.data.token)
        if (event.data.token === 'test-only') ws.close({ code: 4001, reason: 'expired' })
      }))
      await page.goto(`/e2e/harness/index.html?socket=${socket}`)
      await expect.poll(() => refreshes).toBeGreaterThanOrEqual(1)
      await expect(page).not.toHaveURL(/\/login$/)
      await expect.poll(() => tokens).toEqual(['test-only', 'test-only', 'recovered-token'])
      expect(refreshes).toBe(2)
      expect(await page.evaluate(() => (window as any).testAuth.getAccessToken())).toBe('recovered-token')
      expect(await page.evaluate(() => localStorage.getItem('clip_access_token'))).toBeNull()
      await expect(page).not.toHaveURL(/\/login$/)
    })
  }

  for (const refused of [false, true]) {
    test(`${socket} socket ${refused ? 'signs in after a refused refresh' : 'refreshes once after authentication expires'}`, async ({ page }) => {
      let refreshes = 0
      const tokens: string[] = []
      await page.route('**/api/v1/auth/refresh', route => {
        refreshes++
        return route.fulfill({ status: refused ? 401 : 200, json: refused ? {} : {
          access_token: 'socket-renewed', expires_in: 3600, token_type: 'bearer', role: 'student',
        } })
      })
      await page.route('**/login', route => route.fulfill({ contentType: 'text/html',
        body: '<!doctype html><h1>Sign in</h1>' }))
      await page.routeWebSocket('**/ws/session', ws => {
        ws.onMessage(message => {
          const event = JSON.parse(String(message))
          if (event.type !== 'auth') return
          tokens.push(event.data.token)
          if (event.data.token === 'test-only') ws.close({ code: 4001, reason: 'expired' })
        })
      })
      await page.goto(`/e2e/harness/index.html?socket=${socket}`)
      if (refused) {
        await expect(page).toHaveURL(/\/login$/)
        expect(tokens).toEqual(['test-only'])
      } else {
        await expect.poll(() => tokens).toEqual(['test-only', 'socket-renewed'])
        await expect(page).not.toHaveURL(/\/login$/)
      }
      expect(refreshes).toBe(1)
    })
  }

  test(`${socket} socket does not loop when the renewed credential is rejected`, async ({ page }) => {
    let refreshes = 0
    const tokens: string[] = []
    await page.route('**/api/v1/auth/refresh', route => {
      refreshes++
      return route.fulfill({ json: { access_token: 'still-refused', expires_in: 3600 } })
    })
    await page.route('**/login', route => route.fulfill({ contentType: 'text/html', body: '<h1>Sign in</h1>' }))
    await page.routeWebSocket('**/ws/session', ws => ws.onMessage(message => {
      const event = JSON.parse(String(message))
      if (event.type === 'auth') {
        tokens.push(event.data.token)
        ws.close({ code: 4001, reason: 'refused' })
      }
    }))
    await page.goto(`/e2e/harness/index.html?socket=${socket}`)
    await expect(page).toHaveURL(/\/login$/)
    expect(tokens).toEqual(['test-only', 'still-refused'])
    expect(refreshes).toBe(1)
  })

  test(`${socket} socket reconnect authenticates with the refreshed token`, async ({ page }) => {
    const tokens: string[] = []
    const connections: WebSocketRoute[] = []
    await page.routeWebSocket('**/ws/session', ws => {
      connections.push(ws)
      ws.onMessage(message => {
        const event = JSON.parse(String(message))
        if (event.type === 'auth') tokens.push(event.data.token)
      })
    })
    await page.goto(`/e2e/harness/index.html?socket=${socket}`)
    await expect.poll(() => tokens).toEqual(['test-only'])
    // A completed refresh swaps the memory credential without remounting.
    await page.evaluate(() => (window as any).testAuth.saveAccessToken('refreshed-token'))
    connections[0].close({ code: 1012, reason: 'service restart' })
    await expect.poll(() => tokens).toEqual(['test-only', 'refreshed-token'])
  })

  test(`${socket} socket never reuses a token removed before reconnect`, async ({ page }) => {
    const tokens: string[] = []
    const connections: WebSocketRoute[] = []
    // This isolated build contains only the harness, not the production login
    // entry. Serve the redirect target so branded browsers do not show their
    // own error document for the harness server's 404.
    await page.route('**/login', route => route.fulfill({
      contentType: 'text/html', body: '<!doctype html><title>Sign in</title><h1>Sign in</h1>',
    }))
    await page.routeWebSocket('**/ws/session', ws => {
      connections.push(ws)
      ws.onMessage(message => {
        const event = JSON.parse(String(message))
        if (event.type === 'auth') tokens.push(event.data.token)
      })
    })
    await page.goto(`/e2e/harness/index.html?socket=${socket}`)
    await expect.poll(() => tokens).toEqual(['test-only'])
    await page.evaluate(() => (window as any).testAuth.clearAccessToken())
    connections[0].close({ code: 1012, reason: 'service restart' })
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    expect(tokens).toEqual(['test-only'])
  })
}

test('devices remain off until saved opt-in and explicit enable; denial is recoverable', async ({ page }) => {
  await showIndicators(page)
  await expect(page.getByRole('button', { name: 'Turn on' })).toBeDisabled()
  await optIn(page, 'camera')
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') }
  })
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText('Camera: unavailable. Microphone: off.')).toBeVisible()
  await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Ask about this session')).toBeEnabled()
})

test('microphone denial and consent-save failure never strand the interface', async ({ page }) => {
  await page.route('**/api/v1/auth/consent', route => route.fulfill({ status: 503, json: {} }))
  await showIndicators(page)
  await page.getByLabel('I opt in to microphone indicators').check()
  await page.getByRole('button', { name: 'Save my choice' }).click()
  await expect(page.getByRole('alert')).toContainText('No device was started')
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
  await page.unroute('**/api/v1/auth/consent')
  await page.getByRole('button', { name: 'Save my choice' }).click()
  await expect(page.getByRole('button', { name: 'Turn on' })).toBeEnabled()
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError') }
  })
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText('Camera: off. Microphone: unavailable.')).toBeVisible()
})

test('the panel is one line until opened, and a remembered choice starts from it', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Camera and microphone indicators' })).toBeVisible()
  await expect(page.getByLabel('I opt in to camera indicators')).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Start indicators' })).toHaveCount(0)
  await optIn(page, 'camera')
  await page.getByRole('button', { name: 'Hide options' }).click()
  await expect(page.getByLabel('I opt in to camera indicators')).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Start indicators' })).toBeEnabled()
})

test('collapsed indicators keep sensing until Stop is explicitly activated', async ({ page }) => {
  await optIn(page, 'camera')
  await page.getByRole('button', { name: 'Turn on', exact: true }).click()
  await expect(page.getByText('Local sensing active — raw media is not uploaded', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Hide options' }).click()
  await expect(page.getByLabel('I opt in to camera indicators')).not.toBeVisible()
  expect(await page.evaluate(() => (window as any).probe.tracks.some((track: MediaStreamTrack) => track.readyState === 'live'))).toBe(true)
  await page.getByRole('button', { name: 'Stop indicators', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
  await expect(page.getByRole('button', { name: 'Start indicators', exact: true })).toBeEnabled()
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
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect.poll(() => page.evaluate(() => typeof (window as any).releasePermission)).toBe('function')
  await page.getByRole('button', { name: 'Turn everything off' }).click()
  await page.evaluate(() => (window as any).releasePermission())
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState))).toEqual(['ended'])
  await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
})

for (const sensor of ['camera', 'microphone'] as const) {
  test(`${sensor}: real local model startup, derived summaries and shutdown under CPU throttling`, async ({ page, context }, info) => {
    const external: string[] = []
    context.on('request', request => {
      if (!request.url().startsWith('http://127.0.0.1:4174/') && !request.url().startsWith('blob:')) external.push(request.url())
    })
    const cdp = await context.newCDPSession(page)
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
    await optIn(page, sensor)
    const start = Date.now()
    await page.getByRole('button', { name: 'Turn on' }).click()
    await expect(page.getByRole('button', { name: `Stop ${sensor}`, exact: true })).toBeVisible({ timeout: 60_000 })
    const startupMs = Date.now() - start
    await expect.poll(() => page.evaluate(() => (window as any).probe.summaries.length), { timeout: 15_000 }).toBeGreaterThan(0)
    // Ready alone is insufficient: require an actual observation from inference.
    await expect.poll(() => page.evaluate(sensor => (window as any).probe.summaries.some(
      (summary: { face_present: boolean | null; speaking: boolean | null }) =>
        (sensor === 'camera' ? summary.face_present : summary.speaking) !== null,
    ), sensor), { timeout: 15_000 }).toBe(true)
    const summaries = await page.evaluate(() => (window as any).probe.summaries)
    for (const summary of summaries) {
      expect(Object.keys(summary).sort()).toEqual(['face_present', 'gaze_on_screen_ratio', 'speaking', 'window_seconds'])
      expect(summary.window_seconds).toBeGreaterThan(0)
      expect(summary.window_seconds).toBeLessThanOrEqual(3600)
    }
    expect(external).toEqual([])
    const measurement = { browser: context.browser()?.version(), sensor, startupMs, cpuThrottle: 4, summaries, externalRequests: external }
    console.log('Synthetic local-AI measurement:', JSON.stringify(measurement))
    await info.attach(`${sensor}-synthetic-performance.json`, { body: JSON.stringify(measurement), contentType: 'application/json' })
    await page.getByRole('button', { name: 'Turn everything off' }).click()
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))).toBe(true)
    await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
  })
}

for (const action of ['Toggle session connection', 'Toggle sensor mount', 'Reject consent', 'pagehide', 'hidden']) {
  test(`camera releases tracks on ${action}`, async ({ page }) => {
    await optIn(page, 'camera')
    await page.getByRole('button', { name: 'Turn on' }).click()
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
  await showIndicators(page)
  const checkbox = page.getByLabel('I opt in to camera indicators')
  await checkbox.focus()
  await page.keyboard.press('Space')
  await expect(checkbox).toBeChecked()
  await page.keyboard.press('Tab') // microphone checkbox
  await page.keyboard.press('Tab') // save
  await expect(page.getByRole('button', { name: 'Save my choice' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Turn on' })).toBeEnabled()
  await page.getByRole('button', { name: 'Save my choice' }).focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Turn on' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Stop camera', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Turn everything off' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
})

test('missing self-hosted face model stops capture and explains unavailability', async ({ page }) => {
  await page.route('**/attention/**/face_landmarker.task', route => route.abort())
  await page.route('**/attention/face_landmarker.task', route => route.abort())
  await optIn(page, 'camera')
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText('Camera: unavailable. Microphone: off.')).toBeVisible({ timeout: 40_000 })
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))).toBe(true)
})

test('both sensors stop independently and disabling releases every track', async ({ page }) => {
  await showIndicators(page)
  await page.getByLabel('I opt in to camera indicators').check()
  await page.getByLabel('I opt in to microphone indicators').check()
  await page.getByRole('button', { name: 'Save my choice' }).click()
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByRole('button', { name: 'Stop camera', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: 'Stop microphone', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Stop camera', exact: true }).click()
  await expect(page.getByText('Camera: off. Microphone: on.')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map(
    (track: MediaStreamTrack) => ({ kind: track.kind, state: track.readyState }),
  ))).toContainEqual({ kind: 'audio', state: 'live' })
  await page.getByRole('button', { name: 'Turn everything off' }).click()
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every(
    (track: MediaStreamTrack) => track.readyState === 'ended',
  ))).toBe(true)
  await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
})

for (const sensor of ['camera', 'microphone'] as const) {
  test(`${sensor} stops on remote monitoring withdrawal and never auto-resumes`, async ({ page }) => {
    await optIn(page, sensor)
    await page.getByRole('button', { name: 'Turn on' }).click()
    await expect(page.getByRole('button', { name: `Stop ${sensor}`, exact: true })).toBeVisible({ timeout: 60_000 })
    await page.route('**/api/v1/auth/me', route => route.fulfill({ json: {
      id: 'student', role: 'student', consents: [],
    } }))
    await expect(page.getByRole('alert')).toContainText('Monitoring consent is unavailable', { timeout: 10_000 })
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every(
      (track: MediaStreamTrack) => track.readyState === 'ended',
    ))).toBe(true)
    const before = await page.evaluate(() => (window as any).probe.requests)
    await page.getByRole('button', { name: 'Toggle session connection' }).click()
    await page.getByRole('button', { name: 'Toggle session connection' }).click()
    await expect(page.getByText('Local sensing off', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Turn on' })).toBeDisabled()
    expect(await page.evaluate(() => (window as any).probe.requests)).toBe(before)
  })
}

test('failed consent recheck releases the microphone while chat stays usable', async ({ page }) => {
  await optIn(page, 'microphone')
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByRole('button', { name: 'Stop microphone', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.route('**/api/v1/auth/me', route => route.fulfill({ status: 503, json: {} }))
  await expect(page.getByRole('alert')).toContainText('Consent could not be verified', { timeout: 10_000 })
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every(
    (track: MediaStreamTrack) => track.readyState === 'ended',
  ))).toBe(true)
  await expect(page.getByLabel('Ask about this session')).toBeEnabled()
})

test('a missing VAD model releases audio and reports unavailability', async ({ page }) => {
  await page.route('**/attention/vad/*.onnx', route => route.abort())
  await optIn(page, 'microphone')
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText('Camera: off. Microphone: unavailable.')).toBeVisible({ timeout: 40_000 })
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.every(
    (track: MediaStreamTrack) => track.readyState === 'ended',
  ))).toBe(true)
})

test('unsupported insecure context never requests a device', async ({ page }) => {
  await optIn(page, 'camera')
  await page.evaluate(() => Object.defineProperty(window, 'isSecureContext', { value: false }))
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByText('Camera: unavailable. Microphone: off.')).toBeVisible()
  expect(await page.evaluate(() => (window as any).probe.requests)).toBe(0)
})

test('student controls pass automated WCAG checks at narrow width and during chat', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 740 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const builder = () => new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
  const initial = await builder().analyze()
  await info.attach('accessibility-initial.json', { body: JSON.stringify(initial), contentType: 'application/json' })
  expect(initial.violations).toEqual([])
  await page.getByLabel('Ask about this session').fill('Help me reason')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByText('Start with the first principle.')).toBeVisible()
  const streaming = await builder().analyze()
  await info.attach('accessibility-streaming.json', { body: JSON.stringify(streaming), contentType: 'application/json' })
  expect(streaming.violations).toEqual([])
  await page.getByRole('button', { name: 'Stop response', exact: true }).click()
})

for (const theme of ['dark', 'contrast']) {
  test(`student controls have no automated WCAG violations in ${theme} theme`, async ({ page }) => {
    await page.evaluate(theme => document.documentElement.classList.add(theme), theme)
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    expect(result.violations).toEqual([])
  })
}

test('a choice already given is remembered and the devices start by themselves', async ({ page }) => {
  for (const consent of ['engagement_monitoring', 'camera', 'microphone']) granted.add(consent)
  await page.reload()
  // The devices start without the panel being opened; its one line can stop them.
  await expect.poll(() => page.evaluate(() => (window as any).probe.requests)).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: 'Stop indicators' })).toBeVisible()
  await showIndicators(page)
  await expect(page.getByLabel('I opt in to camera indicators')).toBeChecked()
  await expect(page.getByLabel('I opt in to microphone indicators')).toBeChecked()
  await expect.poll(() => page.evaluate(() => (window as any).probe.requests)).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Turn everything off' }).click()
  await expect(page.getByText('Camera: off. Microphone: off.')).toBeVisible()
})
