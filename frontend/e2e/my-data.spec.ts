import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const request = { request_id: 'r', status: 'requested', requested_at: '2026-11-01T10:00:00Z', decided_at: null, executed_at: null }
const absent = { status: 404, json: { error: { code: 'NOT_FOUND', message: 'No request yet.' } } }

test('status loading retries and preserves an unsent reason during a failed refresh', async ({ page }) => {
  let failed = true
  await page.route('**/api/v1/me/deletion-request', route => route.fulfill(failed
    ? { status: 503, json: { error: { message: 'Please try status again.' } } } : absent))
  await page.goto('/e2e/harness/index.html?socket=mydata')
  await expect(page.getByRole('alert')).toContainText('Please try status again.')
  failed = false
  await page.getByRole('button', { name: 'Refresh request status' }).click()
  await page.getByRole('button', { name: 'Ask to erase my data' }).click()
  await page.getByLabel('Reason').fill('Keep my reason while offline.')
  failed = true
  await page.getByRole('button', { name: 'Refresh request status' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Reason')).toHaveValue('Keep my reason while offline.')
  await page.getByRole('checkbox').check()
  await expect(page.getByRole('button', { name: 'Send the request' })).toBeDisabled()
  failed = false
  await page.getByRole('button', { name: 'Refresh request status' }).click()
  await expect(page.getByRole('button', { name: 'Send the request' })).toBeEnabled()
})

test('a request already filed in another tab is reconciled after conflict', async ({ page }) => {
  let filed = false
  let posts = 0
  await page.route('**/api/v1/me/deletion-request', route => {
    if (route.request().method() === 'POST') {
      posts++; filed = true
      return route.fulfill({ status: 409, json: { error: { message: 'Already open.' } } })
    }
    return route.fulfill(filed ? { json: request } : absent)
  })
  await page.goto('/e2e/harness/index.html?socket=mydata')
  await page.getByRole('button', { name: 'Ask to erase my data' }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Send the request' }).click()
  await expect(page.getByText('Waiting for an administrator')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ask to erase my data' })).toHaveCount(0)
  expect(posts).toBe(1)
})

test('pending submission cannot be cancelled and administrator updates refresh on focus', async ({ page }) => {
  let state: typeof request | null = null
  let release: (() => void) | undefined
  let posts = 0
  await page.route('**/api/v1/me/deletion-request', async route => {
    if (route.request().method() === 'POST') {
      posts++
      expect(route.request().postDataJSON()).toEqual({ confirm: true, reason: 'My optional reason' })
      await new Promise<void>(resolve => { release = resolve })
      state = request
      return route.fulfill({ status: 201, json: state })
    }
    return route.fulfill(state ? { json: state } : absent)
  })
  await page.goto('/e2e/harness/index.html?socket=mydata')
  await page.getByRole('button', { name: 'Ask to erase my data' }).click()
  await page.getByLabel('Reason').fill('  My optional reason  ')
  await expect(page.getByRole('button', { name: 'Send the request' })).toBeDisabled()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Send the request' }).click()
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Reason')).toBeDisabled()
  expect(posts).toBe(1)
  release!()
  await expect(page.getByText('Waiting for an administrator')).toBeVisible()
  state = { ...request, status: 'approved' }
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
})

test('export recovers when the browser cannot start the download', async ({ page }) => {
  await page.route('**/api/v1/me/deletion-request', route => route.fulfill(absent))
  await page.route('**/api/v1/me/data', route => route.fulfill({ json: { student: { id: 'own-student' } } }))
  await page.goto('/e2e/harness/index.html?socket=mydata')
  await page.evaluate(() => {
    const original = URL.createObjectURL
    URL.createObjectURL = () => { URL.createObjectURL = original; throw new Error('Download unavailable') }
  })
  await page.getByRole('button', { name: 'Download my data' }).click()
  await expect(page.getByRole('alert')).toContainText('Your data could not be downloaded.')
  await expect(page.getByRole('button', { name: 'Download my data' })).toBeEnabled()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download my data' }).click()
  expect((await download).suggestedFilename()).toBe('my-clip-data.json')
  await expect(page.getByText('Download started: my-clip-data.json.')).toBeVisible()
})

test('an expired token refreshes before exporting and a refused session offers sign-in', async ({ page }) => {
  let renewed = false
  let refused = false
  await page.route('**/api/v1/auth/refresh', route => {
    renewed = true
    return route.fulfill(refused ? { status: 401, json: { error: { message: 'Sign in again.' } } }
      : { json: { access_token: 'fresh-own-token', expires_in: 3600, role: 'student' } })
  })
  await page.route('**/api/v1/auth/logout', route => route.fulfill({ status: 204 }))
  await page.route('**/api/v1/me/deletion-request', route => route.fulfill(absent))
  await page.route('**/api/v1/me/data', route => {
    if (!renewed || refused) return route.fulfill({ status: 401, json: { error: { message: 'Sign in again.' } } })
    expect(route.request().headers().authorization).toBe('Bearer fresh-own-token')
    return route.fulfill({ json: { student: { id: 'own-student' } } })
  })
  await page.goto('/e2e/harness/index.html?socket=mydata')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download my data' }).click()
  await download
  expect(renewed).toBe(true)
  refused = true
  await page.getByRole('button', { name: 'Download my data' }).click()
  await expect(page.getByRole('link', { name: 'Sign in again to open My data' })).toBeVisible()
})

test('My data works at mobile width with keyboard access and automated accessibility checks', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route('**/api/v1/me/deletion-request', route => route.fulfill(absent))
  await page.goto('/e2e/harness/index.html?socket=mydata')
  const ask = page.getByRole('button', { name: 'Ask to erase my data' })
  await ask.focus(); await ask.press('Enter')
  await page.getByRole('checkbox').focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('checkbox')).toBeChecked()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
})

test('a lost response after submission is reconciled without repeating the deletion request', async ({ page }) => {
  let filed = false
  let posts = 0
  await page.route('**/api/v1/me/deletion-request', route => {
    if (route.request().method() === 'POST') {
      filed = true; posts++
      return route.abort('failed')
    }
    return route.fulfill(filed ? { json: request } : absent)
  })
  await page.goto('/e2e/harness/index.html?socket=mydata')
  await page.getByRole('button', { name: 'Ask to erase my data' }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Send the request' }).click()
  await expect(page.getByText('Waiting for an administrator')).toBeVisible()
  expect(posts).toBe(1)
  await expect(page.getByRole('button', { name: 'Send the request' })).toHaveCount(0)
})
