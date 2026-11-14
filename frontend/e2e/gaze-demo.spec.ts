import { expect, test } from '@playwright/test'

// The gaze demo page drops the camera the same way the class panel does.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const probe = { tracks: [] as MediaStreamTrack[] }
    Object.assign(window, { probe })
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await original(constraints)
      probe.tracks.push(...stream.getTracks())
      return stream
    }
  })
  await page.goto('/eval/gaze-demo.html')
})

for (const action of ['pagehide', 'hidden']) {
  test(`gaze demo releases the camera on ${action}`, async ({ page }) => {
    await page.getByRole('button', { name: 'Turn on camera' }).first().click()
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState)),
      { timeout: 30_000 }).toEqual(['live'])
    if (action === 'pagehide') await page.evaluate(() => window.dispatchEvent(new Event('pagehide')))
    else await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState))).toEqual(['ended'])
    await expect(page.getByRole('button', { name: 'Turn off camera' })).toHaveCount(0)
  })
}

test('VAD trial recorder requires consent and releases the microphone on withdrawal', async ({ page }) => {
  await page.goto('/eval/vad-recorder.html')
  const start = page.getByRole('button', { name: 'Start microphone' })
  const consent = page.getByRole('checkbox', { name: 'I agree to run this local microphone trial.' })
  await page.getByLabel('Participant code').fill('P1')
  await start.click()
  await expect(page.getByRole('status')).toHaveText('Enter your assigned code and tick consent.')
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.length)).toBe(0)
  await consent.check()
  await start.click()
  await expect(page.getByRole('button', { name: 'Start quiet trial' })).toBeEnabled({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState))).toEqual(['live'])
  await consent.uncheck()
  await expect.poll(() => page.evaluate(() => (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState))).toEqual(['ended'])
  await expect(page.getByRole('button', { name: 'Start quiet trial' })).toBeDisabled()
})
