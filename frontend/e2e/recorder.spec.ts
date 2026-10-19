import { expect, test, type Page } from '@playwright/test'

// The #159 recorder page. The camera prompt is held open until the test
// releases it, so a stop or a withdrawal can land while the start waits.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const probe = { tracks: [] as MediaStreamTrack[], release: null as null | (() => Promise<void>) }
    Object.assign(window, { probe })
    navigator.mediaDevices.getUserMedia = constraints => new Promise(resolve => {
      probe.release = async () => {
        const stream = await original(constraints)
        probe.tracks.push(...stream.getTracks())
        resolve(stream)
      }
    })
  })
  await page.goto('/eval/attention-recorder.html')
  await page.getByLabel('I agree to my face being analysed').check()
  await page.getByRole('button', { name: 'Start camera' }).click()
  await page.waitForFunction(() => (window as any).probe.release)
})

async function releaseCamera(page: Page) {
  await page.evaluate(() => (window as any).probe.release())
  await page.waitForTimeout(500)
  return page.evaluate(() => ({
    tracks: (window as any).probe.tracks.map((t: MediaStreamTrack) => t.readyState),
    preview: Boolean((document.getElementById('preview') as HTMLVideoElement).srcObject),
    status: document.getElementById('status')!.textContent,
  }))
}

test('withdrawing consent while the camera prompt is open leaves the camera off', async ({ page }) => {
  await page.getByLabel('I agree to my face being analysed').uncheck()
  await expect(page.getByText('Consent withdrawn. Camera off.')).toBeVisible()
  expect(await releaseCamera(page)).toEqual({ tracks: ['ended'], preview: false, status: 'Consent withdrawn. Camera off.' })
  await expect(page.getByRole('button', { name: 'Start camera' })).toBeDisabled()
})

test('stopping while the camera prompt is open leaves the camera off', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Start camera' })).toBeDisabled()
  await page.getByRole('button', { name: 'Stop camera' }).click()
  expect(await releaseCamera(page)).toEqual({ tracks: ['ended'], preview: false, status: 'Camera off.' })
  await expect(page.getByRole('button', { name: 'Start camera' })).toBeEnabled()
})
