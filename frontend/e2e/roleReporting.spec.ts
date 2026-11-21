import { expect, test } from '@playwright/test'

const courseA = { id: 'a', code: 'COURSEA', name: 'Course A' }
const courseB = { id: 'b', code: 'COURSEB', name: 'Course B' }
const person = (id: string, name: string) => ({ id, name, email: `${id}@example.test`, home_course: false })
const assigned = person('assigned', 'Assigned lecturer')
const extra = person('extra', 'Extra lecturer')
const learnerA = person('student-a', 'Student A')
const learnerB = person('student-b', 'Student B')
const emptyPage = { items: [], limit: 50, offset: 0, total: 0 }

test('course roster ignores a previous course response and can assign lecturers beyond page one', async ({ page }) => {
  const rosterA = { course: courseA, lecturers: [], students: [learnerA] }
  const rosterB = { course: courseB, lecturers: [assigned], students: [learnerB] }
  let releaseA!: () => void
  const holdA = new Promise<void>((resolve) => { releaseA = resolve })
  await page.route('**/api/v1/auth/me', route => route.fulfill({ json: { role: 'admin' } }))
  await page.route('**/api/v1/courses/mine', route => route.fulfill({ json: [courseA, courseB] }))
  await page.route('**/api/v1/courses/*/attendance', route => route.fulfill({ json: {
    course_code: courseB.code,
    classes: [
      { session_id: 'morning', title: 'Morning checkpoint', starts_at: '2026-11-01T09:00:00Z' },
      { session_id: 'afternoon', title: 'Afternoon checkpoint', starts_at: '2026-11-01T12:00:00Z' },
    ],
    students: [
      { student_id: learnerB.id, name: learnerB.name, email: learnerB.email, attended: 1,
        classes: [false, true], not_yet_enrolled: ['morning'] },
    ],
  } }))
  await page.route('**/api/v1/courses/COURSEA/roster', async route => {
    await holdA
    await route.fulfill({ json: rosterA })
  })
  await page.route('**/api/v1/courses/COURSEB/roster', route => route.fulfill({ json: rosterB }))
  await page.route('**/api/v1/admin/accounts?*', route => {
    const query = new URL(route.request().url()).searchParams
    if (query.get('role') !== 'lecturer') return route.fulfill({ json: emptyPage })
    if (query.get('q') === 'Extra') {
      return route.fulfill({ json: { ...emptyPage, items: [extra], total: 1 } })
    }
    const offset = Number(query.get('offset'))
    const items = offset === 0
      ? Array.from({ length: 50 }, (_, index) => person(`lecturer-${index}`, `Lecturer ${index}`))
      : [extra]
    return route.fulfill({ json: { ...emptyPage, items, offset, total: 51 } })
  })
  await page.route('**/api/v1/courses/COURSEB/lecturers', route => {
    expect(route.request().postDataJSON()).toEqual({ lecturer_ids: [assigned.id, extra.id] })
    return route.fulfill({ json: { ...rosterB, lecturers: [assigned, extra] } })
  })

  const firstRequest = page.waitForRequest('**/api/v1/courses/COURSEA/roster')
  await page.goto('/e2e/harness/index.html?socket=course-rosters')
  await firstRequest
  await page.getByLabel('Course', { exact: true }).selectOption(courseB.code)
  await expect(page.getByRole('heading', { name: 'Students (1)' })).toBeVisible()
  const firstResponse = page.waitForResponse('**/api/v1/courses/COURSEA/roster')
  releaseA()
  await firstResponse
  await expect(page.getByText(learnerA.name, { exact: true })).toHaveCount(0)
  await expect(page.getByRole('columnheader', { name: /Morning checkpoint/ })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: /Afternoon checkpoint/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Not yet enrolled' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '1 of 1' })).toBeVisible()

  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Extra lecturer/ })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /Assigned lecturer/ })).toBeChecked()
  await page.getByLabel('Find a lecturer').fill('Extra')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: /Extra lecturer/ })).toBeVisible()
  await page.getByRole('checkbox', { name: /Extra lecturer/ }).click()
  await expect(page.getByRole('checkbox', { name: /Extra lecturer/ })).toBeChecked()
})

test('lecturer results include unanswered checkpoints and can retry attendance', async ({ page }) => {
  let attendanceAttempts = 0
  await page.route('**/api/v1/sessions/report-fixture', route => route.fulfill({ json: {
    id: 'report-fixture', course_code: 'COURSEA', title: 'A test lecture', status: 'ended', questions_delivered: 2,
    starts_at: '2026-11-01T09:00:00Z', ended_at: '2026-11-01T10:00:00Z',
  } }))
  await page.route('**/api/v1/sessions/report-fixture/responses?*', route => route.fulfill({ json: {
    items: [], total: 0,
  } }))
  await page.route('**/api/v1/sessions/report-fixture/topics', route => route.fulfill({ json: [] }))
  await page.route('**/api/v1/sessions/report-fixture/breakdown', route => route.fulfill({ json: {
    session_id: 'report-fixture', students: [],
    questions: [1, 2].map(number => ({
      number, question_id: `q${number}`, prompt: `Checkpoint ${number}`, options: null, eligible: 1,
      answers: 0, correct: 0, marked: 0, median_seconds: null,
    })),
  } }))
  await page.route('**/api/v1/sessions/report-fixture/attendance', route => {
    attendanceAttempts += 1
    return attendanceAttempts === 1
      ? route.fulfill({ status: 503, json: { error: { message: 'Try again.' } } })
      : route.fulfill({ json: {
        present: 1, total: 1,
        students: [{ ...learnerA, student_id: learnerA.id, present: true, sources: ['clip'], minutes: 50,
          first_seen: '2026-11-01T09:05:00Z', last_seen: '2026-11-01T09:55:00Z' }],
      } })
  })
  await page.goto('/e2e/harness/index.html?socket=session-results')
  await expect(page.getByText('Question 2: 0 answers', { exact: true })).toBeAttached()
  await expect(page.getByRole('alert')).toContainText('Attendance could not be loaded')
  await page.getByRole('button', { name: 'Retry attendance' }).click()
  await expect(page.getByText(/First seen/)).toBeVisible()
  await expect(page.getByText(/Last seen/)).toBeVisible()
  await expect(page.getByText('50 min', { exact: true })).toHaveCount(0)
})
