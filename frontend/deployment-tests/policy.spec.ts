import { expect, test } from '@playwright/test'

const policies = [
  { path: '/privacy', heading: 'Privacy notice' },
  { path: '/terms', heading: 'Terms of use' },
]

for (const policy of policies) {
  test(`${policy.path} opens signed out and survives reload`, async ({ page }) => {
    await page.goto(policy.path)

    await expect(page).toHaveURL(new RegExp(`${policy.path}$`))
    await expect(
      page.getByRole('heading', { name: policy.heading, exact: true }),
    ).toBeVisible()

    await page.reload()

    await expect(
      page.getByRole('heading', { name: policy.heading, exact: true }),
    ).toBeVisible()

    await expect(page).not.toHaveURL(/\/login/)
  })
}

test('policy pages link to one another', async ({ page }) => {
  await page.goto('/privacy')

  await page.getByRole('link', { name: 'terms of use' }).click()

  await expect(page).toHaveURL(/\/terms$/)
  await expect(page.getByRole('heading', { name: 'Terms of use' })).toBeVisible()

  await page.getByRole('link', { name: 'privacy notice' }).click()

  await expect(page).toHaveURL(/\/privacy$/)
})

test('policy links work with keyboard activation', async ({ page }) => {
  await page.goto('/privacy')

  const termsLink = page.getByRole('link', { name: 'terms of use' })
  await termsLink.focus()
  await expect(termsLink).toBeFocused()

  await page.keyboard.press('Enter')

  await expect(page).toHaveURL(/\/terms$/)
})

test('policy pages fit a mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })

  for (const policy of policies) {
    await page.goto(policy.path)
    await expect(
      page.getByRole('heading', { name: policy.heading, exact: true }),
    ).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    )

    expect(hasHorizontalOverflow).toBe(false)
  }
})
