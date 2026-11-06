import { expect, test } from '@playwright/test'

// Real browser -> nginx -> API -> PostgreSQL. Development accounts only;
// no media permissions, mocked API, stored bearer or production login bypass.
for (const account of [
  { role: 'student', password: 'StudentPass123!', home: '/student', heading: /Hello,/,
    detail: '/student/reviews', detailHeading: 'Past sessions' },
  { role: 'lecturer', password: 'LecturerPass123!', home: '/lecturer/sessions', heading: 'Sessions',
    detail: '/lecturer/materials', detailHeading: 'Materials' },
  { role: 'admin', password: 'AdminPass123!', home: '/admin', heading: 'Imports',
    detail: '/admin/governance', detailHeading: 'Governance' },
]) {
  test(`${account.role}: real sign-in, role page, reload and sign-out`, async ({ page, context }) => {
    const health = await page.request.get('/api/v1/health')
    expect(health.ok()).toBeTruthy()
    expect((await health.json()).env).toBe('development')
    const errors: string[] = []
    const serverErrors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      if (response.url().includes('/api/') && response.status() >= 500) {
        serverErrors.push(`${response.status()} ${new URL(response.url()).pathname}`)
      }
    })
    await page.goto('/login')
    await page.getByLabel('Email', { exact: true }).fill(`${account.role}@clip.example.com`)
    await page.getByLabel('Password', { exact: true }).fill(account.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`(${account.home}|/consent)$`))
    if (new URL(page.url()).pathname === '/consent') {
      const terms = page.getByRole('checkbox', { name: /I accept the C.L.I.P terms/ })
      await terms.focus()
      await terms.press('Space')
      await expect(terms).toBeChecked()
      await page.getByRole('button', { name: 'Continue', exact: true }).click()
    }
    await expect(page.getByRole('heading', { name: account.heading, level: 1 })).toBeVisible()
    const cookies = await context.cookies()
    expect(cookies.some(cookie => cookie.name === 'clip_refresh' && cookie.httpOnly)).toBeTruthy()
    expect(await page.evaluate(() => localStorage.getItem('clip_access_token'))).toBeNull()
    await page.goto(account.detail)
    await expect(page.getByRole('heading', { name: account.detailHeading, level: 1 })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { name: account.detailHeading, level: 1 })).toBeVisible()
    if (account.role === 'student') {
      await page.goto('/admin/status')
      await expect(page).toHaveURL(/\/access-denied$/)
    } else {
      await page.goto('/student/my-data')
      await expect(page).toHaveURL(/\/access-denied$/)
    }
    // The real shell waits for logout's cookie clearing before navigating.
    await page.goto(account.home)
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.reload()
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
    expect((await context.cookies()).some(cookie => cookie.name === 'clip_refresh')).toBeFalsy()
    expect(errors).toEqual([])
    expect(serverErrors).toEqual([])
  })
}

test('student can use My data after withdrawing terms', async ({ page }) => {
  const health = await page.request.get('/api/v1/health')
  expect(health.ok()).toBeTruthy()
  expect((await health.json()).env).toBe('development')
  const credentials = { email: 'student@clip.example.com', password: 'StudentPass123!' }
  const login = await page.request.post('/api/v1/auth/login', { data: credentials })
  expect(login.ok()).toBeTruthy()
  const { access_token } = await login.json()
  const headers = { Authorization: `Bearer ${access_token}` }
  const withdrawal = await page.request.post('/api/v1/auth/consent', {
    headers,
    data: { consent_type: 'terms', granted: false },
  })
  expect(withdrawal.ok()).toBeTruthy()

  await page.goto('/student/reviews')
  await expect(page).toHaveURL(/\/consent$/)
  const dataLink = page.getByRole('link', { name: 'Open My data' })
  await dataLink.focus()
  await dataLink.press('Enter')
  await expect(page.getByRole('heading', { name: 'My data', level: 1 })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'My data', level: 1 })).toBeVisible()

  const download = page.waitForEvent('download')
  const exportResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/me/data')
  await page.getByRole('button', { name: 'Download my data' }).click()
  expect((await download).suggestedFilename()).toBe('my-clip-data.json')
  expect((await exportResponse).headers()['cache-control']).toContain('no-store')
  await page.getByRole('button', { name: 'Ask to erase my data' }).click()
  const sendRequest = page.getByRole('button', { name: 'Send the request' })
  await expect(sendRequest).toBeDisabled()
  await page.getByRole('checkbox', { name: /I understand my data will be erased/ }).check()
  await sendRequest.click()
  await expect(page.getByText('Waiting for an administrator')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ask to erase my data' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/student/my-data')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Email', { exact: true }).fill(credentials.email)
  await page.getByLabel('Password', { exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/student\/my-data$/)
  await expect(page.getByRole('heading', { name: 'My data', level: 1 })).toBeVisible()
})
