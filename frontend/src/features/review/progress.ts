import type { ReviewAnswer, StudentReview } from './reviewTypes.ts'

export type Mastery = 'mastered' | 'partial' | 'struggling'

export interface TopicMark {
  sessionId: string
  title: string
  /** How the topic went in that session, or null when it did not come up. */
  level: Mastery | null
}

export interface TopicProgress {
  topic: string
  marks: TopicMark[]
  /** The most recent session's word on it: a topic struggled with in week 3
   * and mastered in week 8 is mastered. */
  latest: Mastery
  answered: number
}

const SCORE: Record<Mastery, number> = { mastered: 1, partial: 0.5, struggling: 0 }

/** What one answer says about its topic. An unmarked answer says nothing,
 * and a label the classifier was unsure of is left out rather than trusted. */
function answerScore(answer: ReviewAnswer): number | null {
  if (answer.label && (answer.confidence === null || answer.confidence >= 0.6)) return SCORE[answer.label]
  if (answer.is_correct === true) return 1
  if (answer.is_correct === false) return 0
  return null
}

function level(scores: number[]): Mastery | null {
  if (scores.length === 0) return null
  const mean = scores.reduce((sum, score) => sum + score, 0) / scores.length
  return mean >= 0.75 ? 'mastered' : mean >= 0.4 ? 'partial' : 'struggling'
}

/**
 * Every topic across a student's finished sessions, oldest session first.
 * Built only from their own marked answers: nothing about anyone else, and
 * engagement plays no part in it.
 */
export function topicProgress(reviews: readonly StudentReview[]): TopicProgress[] {
  const sessions = [...reviews].sort(
    (a, b) => Date.parse(a.session.ended_at ?? '') - Date.parse(b.session.ended_at ?? ''),
  )
  const topics = new Map<string, Map<string, number[]>>()
  for (const review of sessions) {
    for (const answer of review.answers) {
      const score = answerScore(answer)
      if (score === null || !answer.topic?.trim()) continue
      const topic = answer.topic.trim()
      const bySession = topics.get(topic) ?? new Map<string, number[]>()
      bySession.set(review.session.id, [...(bySession.get(review.session.id) ?? []), score])
      topics.set(topic, bySession)
    }
  }

  return [...topics].map(([topic, bySession]) => {
    const marks = sessions.map((review) => ({
      sessionId: review.session.id,
      title: review.session.title,
      level: level(bySession.get(review.session.id) ?? []),
    }))
    const latest = [...marks].reverse().find((mark) => mark.level !== null)?.level ?? 'partial'
    const answered = [...bySession.values()].reduce((sum, scores) => sum + scores.length, 0)
    return { topic, marks, latest, answered }
  })
}

const RANK: Record<Mastery, number> = { struggling: 0, partial: 1, mastered: 2 }

/** What to revisit first, then the rest by name. */
export function revisitFirst(topics: readonly TopicProgress[]): TopicProgress[] {
  return [...topics].sort((a, b) => RANK[a.latest] - RANK[b.latest] || a.topic.localeCompare(b.topic))
}
