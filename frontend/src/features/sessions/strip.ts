import type { SessionResponse } from './sessionsApi'

/** One delivered question as the session strip draws it. */
export interface StripQuestion {
  questionId: string
  /** 1 for the first question the class answered, in the order they came. */
  position: number
  right: number
  wrong: number
  /** Free text still being marked, or never marked. */
  unmarked: number
}

/** The session's questions in the order they were first answered, with how
 * the answers went. Built from stored responses, so it works after the
 * session as well as during it. */
export function stripFromResponses(responses: readonly SessionResponse[]): StripQuestion[] {
  const byQuestion = new Map<string, { first: number; right: number; wrong: number; unmarked: number }>()
  for (const response of responses) {
    const at = Date.parse(response.submitted_at)
    const entry = byQuestion.get(response.question_id) ?? {
      first: Number.POSITIVE_INFINITY,
      right: 0,
      wrong: 0,
      unmarked: 0,
    }
    entry.first = Math.min(entry.first, Number.isFinite(at) ? at : Number.POSITIVE_INFINITY)
    if (response.is_correct === true) entry.right += 1
    else if (response.is_correct === false) entry.wrong += 1
    else entry.unmarked += 1
    byQuestion.set(response.question_id, entry)
  }
  return [...byQuestion.entries()]
    .sort(([a, x], [b, y]) => x.first - y.first || a.localeCompare(b))
    .map(([questionId, entry], index) => ({
      questionId,
      position: index + 1,
      right: entry.right,
      wrong: entry.wrong,
      unmarked: entry.unmarked,
    }))
}

export function describeQuestion(question: StripQuestion): string {
  const answered = question.right + question.wrong + question.unmarked
  const parts = [`Question ${question.position}: ${answered} ${answered === 1 ? 'answer' : 'answers'}`]
  if (question.right + question.wrong > 0) parts.push(`${question.right} right, ${question.wrong} wrong`)
  if (question.unmarked > 0) parts.push(`${question.unmarked} not marked yet`)
  return parts.join(', ')
}
