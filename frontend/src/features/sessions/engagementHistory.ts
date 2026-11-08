import type { QuietStudent, SessionEngagement } from './engagementHistoryApi'

export function percent(value: number | null): string {
  return value === null ? 'No data' : `${Math.round(value * 100)}%`
}

/** Why a student is on the check-in list, in words. */
export function quietReason(student: QuietStudent): string {
  if (student.sessions_missed * 2 > student.sessions_considered) {
    return `Missed ${student.sessions_missed} of the last ${student.sessions_considered} classes`
  }
  return `Answered ${percent(student.answer_rate)} of checkpoints in the last ${student.sessions_considered} classes`
}

/** The course codes in the history, in the order they first appear. */
export function coursesOf(sessions: SessionEngagement[]): string[] {
  return [...new Set(sessions.map((session) => session.course_code))]
}

/** Change in answer rate between the newest class and the average of the
 * ones before it, or null when there is nothing to compare. */
export function answerTrend(sessions: SessionEngagement[]): number | null {
  const rates = sessions.map((session) => session.answer_rate).filter((rate): rate is number => rate !== null)
  if (rates.length < 2) return null
  const [latest, ...earlier] = rates
  const average = earlier.reduce((sum, rate) => sum + rate, 0) / earlier.length
  return Math.round((latest - average) * 100) / 100
}
