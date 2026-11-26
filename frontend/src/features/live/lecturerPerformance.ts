import type { SessionResponse } from '../sessions/sessionsApi'

export interface PerformanceAverage {
  /** Mean of each student's marked-answer accuracy, expressed as a percent. */
  average: number
  /** Number of students with at least one marked response. */
  students: number
}

/** Unmarked responses are not treated as wrong. Every student has equal weight. */
export function averageStudentAccuracy(
  responses: readonly Pick<SessionResponse, 'student_id' | 'is_correct'>[],
): PerformanceAverage | null {
  const scores = new Map<string, { marked: number; correct: number }>()

  for (const response of responses) {
    if (response.is_correct === null) continue
    const score = scores.get(response.student_id) ?? { marked: 0, correct: 0 }
    score.marked += 1
    if (response.is_correct) score.correct += 1
    scores.set(response.student_id, score)
  }

  if (scores.size === 0) return null

  const studentPercentages = Array.from(
    scores.values(),
    (score) => (100 * score.correct) / score.marked,
  )

  return {
    average: studentPercentages.reduce((sum, score) => sum + score, 0) / scores.size,
    students: scores.size,
  }
}
