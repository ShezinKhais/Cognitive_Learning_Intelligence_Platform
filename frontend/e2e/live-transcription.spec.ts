import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const captureId = '7bf58ae5-1ede-4663-8205-3a3d684cd034'

test.beforeEach(async ({ page, context }) => {
  await context.grantPermissions(['microphone'])
  await page.addInitScript(() => {
    const probe = { tracks: [] as MediaStreamTrack[], requests: 0 }
    Object.assign(window, { liveProbe: probe })
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async options => {
      probe.requests++
      const stream = await original(options)
      probe.tracks.push(...stream.getTracks())
      return stream
    }
  })
  let active = false
  await page.route('**/live-transcription**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/start')) { active = true; return route.fulfill({ json: { configured: true, running: true, session_running: true, capture_id: captureId, language: 'en' } }) }
    if (path.endsWith('/stop')) { active = false; return route.fulfill({ json: { stopped: true } }) }
    if (path.includes('/chunks/')) return route.fulfill({ json: { sequence: 0, note: null } })
    return route.fulfill({ json: { configured: true, running: active, session_running: true, capture_id: active ? captureId : null, language: 'en' } })
  })
  await page.route('**/discussion/automatic-transcripts', route => route.fulfill({ json: { configured: false, enabled: false, subscribed: false, message: 'Automatic fetching disabled.', drafts: [], pending: 0, failed: 0 } }))
  await page.route('**/discussion/transcripts', route => route.fulfill({ json: { enabled: false, items: [], message: 'Import disabled.' } }))
  await page.route('**/discussion', route => route.fulfill({ json: { notes: [], latest_recorded_at: null, session_status: 'active' } }))
  await page.goto('/e2e/harness/index.html?socket=discussion&publisher')
})

async function start(page: import('@playwright/test').Page) {
  await page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false }).check()
  await page.getByRole('button', { name: 'Start live transcription' }).click()
  await expect(page.getByText('Microphone live — processing 10-second chunks', { exact: false })).toBeVisible()
}

async function allStopped(page: import('@playwright/test').Page) {
  await expect.poll(() => page.evaluate(() => (window as any).liveProbe.tracks.every((track: MediaStreamTrack) => track.readyState === 'ended'))).toBe(true)
}

test('explicit opt-in starts real local microphone chunks and one-click stop releases tracks', async ({ page }) => {
  let uploaded = 0
  await page.route('**/live-transcription/*/chunks/*', route => {
    const bytes = route.request().postDataBuffer()!
    expect(bytes.subarray(0, 4).toString()).toBe('RIFF')
    expect(bytes.length).toBe(320044)
    uploaded++
    return route.fulfill({ json: { sequence: uploaded - 1, note: null } })
  })
  await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeDisabled()
  expect(await page.evaluate(() => (window as any).liveProbe.requests)).toBe(0)
  await start(page)
  await expect.poll(() => uploaded, { timeout: 20000 }).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Stop live transcription' }).click()
  await allStopped(page)
  await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeDisabled()
})

for (const event of ['visibilitychange', 'pagehide']) {
  test(`${event}: capture stops without automatically restarting`, async ({ page }) => {
    await start(page)
    await page.evaluate(event => {
      if (event === 'visibilitychange') {
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
        document.dispatchEvent(new Event(event))
      } else window.dispatchEvent(new Event(event))
    }, event)
    await allStopped(page)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeDisabled()
  })
}

test('session ending stops capture on the next status check', async ({ page }) => {
  await start(page)
  await page.route('**/live-transcription', route => route.fulfill({ json: { configured: true, running: false, session_running: false, capture_id: null, language: 'en' } }))
  await allStopped(page)
  await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeDisabled()
})

test('permission denial is recoverable and never starts a server capture', async ({ page }) => {
  let starts = 0
  await page.route('**/live-transcription/start', route => { starts++; return route.fulfill({ status: 500 }) })
  await page.evaluate(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Microphone denied', 'NotAllowedError') } })
  await page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false }).check()
  await page.getByRole('button', { name: 'Start live transcription' }).click()
  await expect(page.getByRole('alert')).toContainText('Microphone denied')
  expect(starts).toBe(0)
  await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeEnabled()
})

test('the lecturer notice and controls are keyboard accessible', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const notice = page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false })
  await notice.focus(); await notice.press('Space')
  await expect(notice).toBeChecked()
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
})

test('stop during a pending microphone prompt releases a late stream without starting capture', async ({ page }) => {
  let serverStarts = 0
  await page.route('**/live-transcription/start', route => { serverStarts++; return route.fulfill({ status: 500 }) })
  await page.evaluate(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = options => new Promise(resolve => {
      Object.assign(window, { releaseMicrophone: async () => resolve(await original(options)) })
    })
  })
  await page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false }).check()
  await page.getByRole('button', { name: 'Start live transcription' }).click()
  await page.getByRole('button', { name: 'Stop live transcription' }).click()
  await page.evaluate(() => (window as any).releaseMicrophone())
  await allStopped(page)
  expect(serverStarts).toBe(0)
})

test('stop while the server start is pending immediately releases the acquired microphone', async ({ page }) => {
  let started = false
  await page.route('**/live-transcription/start', async route => {
    started = true
    await new Promise(resolve => setTimeout(resolve, 3000))
    await route.fulfill({ json: { configured: true, running: true, session_running: true, capture_id: captureId, language: 'en' } }).catch(() => {})
  })
  await page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false }).check()
  await page.getByRole('button', { name: 'Start live transcription' }).click()
  await expect.poll(() => started).toBe(true)
  await page.getByRole('button', { name: 'Stop live transcription' }).click()
  await allStopped(page)
  await expect(page.getByRole('button', { name: 'Start live transcription' })).toBeDisabled()
})

test('a processing backlog stops capture with an explicit gap warning', async ({ page }) => {
  await page.evaluate(() => {
    const Original = window.AudioWorkletNode
    Object.assign(window, { AudioWorkletNode: class extends Original {
      constructor(context: BaseAudioContext, name: string, options?: AudioWorkletNodeOptions) {
        super(context, name, options)
        Object.assign(window, { liveTestNode: this })
      }
    } })
  })
  await page.route('**/live-transcription/*/chunks/*', async route => {
    await new Promise(resolve => setTimeout(resolve, 3000))
    await route.fulfill({ json: { sequence: 0, note: null } }).catch(() => {})
  })
  await start(page)
  await page.evaluate(() => {
    const node = (window as any).liveTestNode as AudioWorkletNode
    for (let i = 0; i < 4; i++) node.port.onmessage!(new MessageEvent('message', { data: { samples: new Float32Array(160000), started: i * 10 } }))
  })
  await expect(page.getByRole('alert')).toContainText('cannot keep up')
  await allStopped(page)
})

test('an already-hidden page cannot request a microphone', async ({ page }) => {
  const confirmed = page.getByRole('checkbox', { name: 'I confirm participants have been informed', exact: false })
  await confirmed.check()
  const button = page.getByRole('button', { name: 'Start live transcription' })
  await expect(button).toBeEnabled()
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  })
  await button.click()
  await expect(button).toBeVisible()
  expect(await page.evaluate(() => (window as any).liveProbe.requests)).toBe(0)
})
