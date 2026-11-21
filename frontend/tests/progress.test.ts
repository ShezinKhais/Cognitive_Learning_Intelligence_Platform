import assert from 'node:assert/strict'
import test from 'node:test'

import { revisitFirst, topicProgress } from '../src/features/review/progress.ts'
import type { ReviewAnswer, StudentReview } from '../src/features/review/reviewTypes.ts'

function answer(topic: string | null, mark: Partial<ReviewAnswer>): ReviewAnswer {
  return { id: crypto.randomUUID(), question: 'Q?', topic, answer: 'A', is_correct: null, label: null, confidence: null, submitted_at: '', ...mark }
}

function review(id: string, endedAt: string, answers: ReviewAnswer[]): StudentReview {
  return {
    session: { id, title: `Session ${id}`, course_code: 'CSIT321', ended_at: endedAt },
    questions_attempted: answers.length, questions_missed: 0,
    engagement: { status: 'unavailable', score: null, explanation: '' },
    answers, total: answers.length, limit: 100, offset: 0,
  }
}

test('a topic is judged by its latest session, oldest session first', () => {
  const topics = topicProgress([
    review('b', '2026-10-16T08:00:00Z', [answer('Gradient descent', { is_correct: true }), answer('Loss', { is_correct: false })]),
    review('a', '2026-10-09T08:00:00Z', [answer('Gradient descent', { is_correct: false })]),
  ])
  const descent = topics.find((t) => t.topic === 'Gradient descent')!
  assert.deepEqual(descent.marks.map((m) => [m.sessionId, m.level]), [['a', 'struggling'], ['b', 'mastered']])
  assert.equal(descent.latest, 'mastered')
  assert.equal(descent.answered, 2)
  const loss = topics.find((t) => t.topic === 'Loss')!
  assert.deepEqual(loss.marks.map((m) => m.level), [null, 'struggling'])
})

test('unmarked, untopical and unsure answers say nothing', () => {
  const topics = topicProgress([
    review('a', '2026-10-09T08:00:00Z', [
      answer('Loss', {}),
      answer(null, { is_correct: true }),
      answer('Bias', { label: 'struggling', confidence: 0.3 }),
      answer('Bias', { label: 'partial', confidence: 0.9 }),
    ]),
  ])
  assert.deepEqual(topics.map((t) => [t.topic, t.latest]), [['Bias', 'partial']])
})

test('what to revisit comes first', () => {
  const topics = topicProgress([
    review('a', '2026-10-09T08:00:00Z', [answer('Zeta', { is_correct: false }), answer('Alpha', { is_correct: true })]),
  ])
  assert.deepEqual(revisitFirst(topics).map((t) => t.topic), ['Zeta', 'Alpha'])
})

test('every page of sessions and of answers is read before topics are worked out', async () => {
  const { allReviews } = await import('../src/features/review/readAll.ts')
  // 3 sessions served 2 a page; the last has 5 answers served 2 a page.
  const sessions = ['a', 'b', 'c'].map((id, i) => ({ id, title: id, course_code: 'C', ended_at: `2026-10-0${i + 1}T08:00:00Z` }))
  const answers = Array.from({ length: 5 }, (_, i) => answer('Loss', { is_correct: i === 4 }))
  const asked: string[] = []
  const read = async <T,>(path: string): Promise<T> => {
    asked.push(path)
    const offset = Number(new URL(path, 'http://x').searchParams.get('offset'))
    if (path.startsWith('/student-reviews?')) {
      return { items: sessions.slice(offset, offset + 2), total: 3, limit: 2, offset } as T
    }
    const id = path.split('/')[2].split('?')[0]
    const mine = id === 'c' ? answers : []
    const page = review(id, sessions.find((s) => s.id === id)!.ended_at, mine.slice(offset, offset + 2))
    return { ...page, total: mine.length } as T
  }
  const { reviews, unavailable } = await allReviews(read)
  assert.deepEqual(unavailable, [])
  assert.equal(reviews.length, 3)
  assert.equal(reviews.find((r) => r.session.id === 'c')!.answers.length, 5)
  // The last answer, on the third page, was right; it is in the result.
  const loss = topicProgress(reviews).find((t) => t.topic === 'Loss')!
  assert.equal(loss.answered, 5)
  assert.equal(asked.filter((p) => p.startsWith('/student-reviews/c')).length, 3)
})


test('a topic name shared by two subjects produces separate progress and histories', () => {
  const maths = review('maths', '2026-10-10T08:00:00Z', [answer('Introduction', { is_correct: true })])
  maths.session.course_code = 'MATH100'
  const coding = review('coding', '2026-10-09T08:00:00Z', [answer('Introduction', { is_correct: false })])
  const topics = topicProgress([maths, coding])
  assert.deepEqual(topics.map((topic) => [topic.courseCode, topic.latest, topic.marks[0].sessionId]), [
    ['CSIT321', 'struggling', 'coding'],
    ['MATH100', 'mastered', 'maths'],
  ])
  assert.notEqual(topics[0].id, topics[1].id)
})

test('progress limits concurrency and can retry just the failed lesson', async () => {
  const { allReviews } = await import('../src/features/review/readAll.ts')
  const fixtures = Array.from({ length: 12 }, (_, i) => review(String(i), '2026-10-09T08:00:00Z', []))
  let active = 0
  let peak = 0
  let failed = true
  const requests: string[] = []
  const read = async <T,>(path: string): Promise<T> => {
    if (path.startsWith('/student-reviews?')) {
      return { items: fixtures.map(({ session }) => session), total: fixtures.length } as T
    }
    const id = path.split('/')[2].split('?')[0]
    requests.push(id)
    peak = Math.max(peak, ++active)
    await Promise.resolve()
    active -= 1
    if (failed && id === '2') throw new Error('Unavailable')
    return fixtures[Number(id)] as T
  }
  const partial = await allReviews(read)
  assert.equal(peak, 4)
  assert.equal(partial.reviews.length, 11)
  assert.deepEqual(partial.unavailable.map(({ id }) => id), ['2'])
  failed = false
  requests.length = 0
  const recovered = await allReviews(read, partial.unavailable)
  assert.deepEqual(requests, ['2'])
  assert.deepEqual(recovered.reviews.map(({ session }) => session.id), ['2'])
  assert.deepEqual(recovered.unavailable, [])
})
