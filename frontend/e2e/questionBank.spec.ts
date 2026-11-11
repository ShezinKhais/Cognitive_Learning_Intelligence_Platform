import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test.describe('Lecturer question bank and lesson selection', () => {
  const question = { id: 'bank-question', material_id: 'material-test', type: 'mcq', status: 'staged', difficulty: 'medium', prompt: 'Which planet is largest?', options: ['Mars', 'Jupiter'], correct_option: 1, topic: 'Planets', source_slide: 3, source_excerpt: 'Jupiter is the largest planet.', material_title: 'Planets.pdf' }
  const emptyPlan = { session_id: 'lesson-test', selected_only: false, editable: true, items: [] as typeof question[] }

  test('manual MCQ source errors retain input, and retry sends the reviewed answer and exact source', async ({ page }) => {
    const payloads: Record<string, unknown>[] = []
    await page.route('**/api/v1/materials/material-test/questions', route => {
      const body = route.request().postDataJSON(); payloads.push(body)
      if (payloads.length === 1) return route.fulfill({ status: 422, json: { error: { code: 'VALIDATION_ERROR', message: 'Source passage does not match.' } } })
      return route.fulfill({ status: 201, json: { ...question, ...body } })
    })
    await page.goto('/e2e/question-bank/index.html?write')
    await page.getByLabel('Question', { exact: true }).fill(question.prompt)
    await page.getByLabel('Option 1', { exact: true }).fill('Mars')
    await page.getByLabel('Option 2', { exact: true }).fill('Jupiter')
    await page.getByLabel('Option 2 is correct').check()
    await page.getByLabel('Source page or slide (optional)').fill('3')
    await page.getByLabel('Exact source passage (optional)').fill('Incorrect passage')
    await page.getByRole('button', { name: 'Save, ready to send' }).click()
    await expect(page.getByRole('alert')).toContainText('Source passage does not match.')
    await expect(page.getByLabel('Question', { exact: true })).toHaveValue(question.prompt)
    await page.getByLabel('Exact source passage (optional)').fill(question.source_excerpt)
    await page.getByRole('button', { name: 'Save, ready to send' }).click()
    await expect(page.getByText(`Saved question: ${question.prompt}`, { exact: true })).toBeVisible()
    expect(payloads[1]).toMatchObject({ correct_option: 1, source_slide: 3, source_excerpt: question.source_excerpt })
    const a11y = await new AxeBuilder({ page }).analyze()
    expect(a11y.violations).toEqual([])
  })

  test('written questions require a reference answer and marking key points', async ({ page }) => {
    let payload: Record<string, unknown> | undefined
    await page.route('**/api/v1/materials/material-test/questions', route => {
      payload = route.request().postDataJSON()
      return route.fulfill({ status: 201, json: { ...question, ...payload } })
    })
    await page.goto('/e2e/question-bank/index.html?write')
    await page.getByRole('radio', { name: 'Written answer' }).check()
    await page.getByLabel('Question', { exact: true }).fill('Explain normalization.')
    await page.getByRole('button', { name: 'Save, ready to send' }).click()
    await expect(page.getByRole('alert')).toContainText('Add a model answer')
    expect(payload).toBeUndefined()
    await page.getByLabel('Model answer', { exact: true }).fill('Normalization reduces duplicated values.')
    await page.getByLabel('Key points', { exact: false }).fill('Reduce duplication\nOrganize relations')
    await page.getByRole('button', { name: 'Save, ready to send' }).click()
    await expect(page.getByText('Saved question: Explain normalization.', { exact: true })).toBeVisible()
    expect(payload?.key_points).toEqual(['Reduce duplication', 'Organize relations'])
  })

  test('lesson selection reviews sources, requires confirmation and survives reload as independent copies', async ({ page }) => {
    let plan = emptyPlan
    let sent: Record<string, unknown> | undefined
    await page.route('**/api/v1/sessions/lesson-test/question-plan**', route => {
      if (route.request().url().includes('/candidates?')) return route.fulfill({ json: { items: [question], total: 1, limit: 10, offset: 0 } })
      if (route.request().method() === 'PUT') {
        sent = route.request().postDataJSON()
        plan = { ...emptyPlan, selected_only: true, items: [{ ...question, id: 'lesson-copy' }] }
      }
      return route.fulfill({ json: plan })
    })
    await page.goto('/e2e/question-bank/index.html')
    await page.getByLabel('Use only selected checkpoints in this lesson').check()
    await expect(page.getByRole('button', { name: 'Start test lesson' })).toBeDisabled()
    await page.getByText('Review answer and source', { exact: true }).click()
    await expect(page.getByText('Jupiter is the largest planet.', { exact: true })).toBeVisible()
    await page.getByRole('checkbox', { name: question.prompt, exact: true }).check()
    await expect(page.getByRole('button', { name: 'Save lesson selection' })).toBeDisabled()
    await page.getByLabel('I reviewed the selected questions', { exact: false }).check()
    await page.getByRole('button', { name: 'Save lesson selection' }).click()
    await expect(page.getByText('Saved 1 checkpoints for this lesson.', { exact: true })).toBeVisible()
    expect(sent).toMatchObject({ selected_only: true, question_ids: [question.id], reviewed_confirmed: true })
    await expect(page.getByRole('button', { name: 'Start test lesson' })).toBeEnabled()
    await expect(page.getByText('Readiness refreshes: 1')).toBeVisible()
    const a11y = await new AxeBuilder({ page }).analyze()
    expect(a11y.violations).toEqual([])
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Selected (1/100)' })).toBeVisible()
    await expect(page.getByRole('button', { name: `Remove ${question.prompt}`, exact: true })).toBeVisible()
  })

  test('filters and candidate pagination keep selections, while a rejected save preserves the draft', async ({ page }) => {
    let sent: Record<string, unknown> | undefined
    await page.route('**/api/v1/sessions/lesson-test/question-plan**', route => {
      if (route.request().url().includes('/candidates?')) {
        const url = new URL(route.request().url())
        const offset = Number(url.searchParams.get('offset'))
        const filtered = Boolean(url.searchParams.get('topic'))
        return route.fulfill({ json: { items: [{ ...question, id: offset ? 'second' : 'first', prompt: offset ? 'Second checkpoint' : question.prompt }], total: filtered ? 1 : 11, limit: 10, offset } })
      }
      if (route.request().method() === 'PUT') {
        sent = route.request().postDataJSON()
        return route.fulfill({ status: 409, json: { error: { code: 'CONFLICT', message: 'Choose before starting the class.' } } })
      }
      return route.fulfill({ json: emptyPlan })
    })
    await page.goto('/e2e/question-bank/index.html')
    await page.getByLabel('Use only selected checkpoints in this lesson').check()
    await page.getByRole('checkbox', { name: question.prompt, exact: true }).check()
    await page.getByRole('navigation', { name: 'Lesson candidate pages' }).getByRole('button', { name: 'Next' }).click()
    await page.getByRole('checkbox', { name: 'Second checkpoint', exact: true }).check()
    await page.getByLabel('Find topic', { exact: true }).fill('Planets')
    await page.getByRole('button', { name: 'Find checkpoints' }).click()
    await expect(page.getByRole('heading', { name: 'Selected (2/100)' })).toBeVisible()
    await page.getByLabel('I reviewed the selected questions', { exact: false }).check()
    await page.getByRole('button', { name: 'Save lesson selection' }).click()
    await expect(page.getByRole('alert')).toContainText('Choose before starting')
    expect(sent?.question_ids).toEqual(['first', 'second'])
    await expect(page.getByRole('button', { name: 'Start test lesson' })).toBeDisabled()
    await page.getByRole('button', { name: 'Discard changes' }).click()
    await expect(page.getByRole('button', { name: 'Start test lesson' })).toBeEnabled()
  })
})
