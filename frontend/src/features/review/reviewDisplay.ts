import type { ReviewAnswer } from './reviewTypes.ts'

export function needsReview(answer: ReviewAnswer): boolean {
  return (
    answer.is_correct === false ||
    answer.label === 'partial' ||
    answer.label === 'struggling'
  )
}

export function comprehensionText(answer: ReviewAnswer): string {
  if (answer.label && answer.confidence !== null && answer.confidence < 0.6) {
    return 'Uncertain classification — ask your lecturer'
  }
  if (answer.label === 'mastered') return 'Mastered'
  if (answer.label === 'partial') return 'Partially understood'
  if (answer.label === 'struggling') return 'Needs more practice'
  if (answer.is_correct === true) return 'Correct answer'
  if (answer.is_correct === false) return 'Review this answer'
  return 'Classification unavailable'
}

export function reviewError(status?: number): string {
  if (status === 401)
    return 'Your session expired. Sign in again to see your review.'
  if (status === 403) return 'Student access and terms consent are required.'
  if (status === 404)
    return 'This review is unavailable. The session may not have ended, or may no longer be assigned to you.'
  if (status === 501)
    return 'Session review is not available on this server yet.'
  return 'Could not load this review. Check your connection and try again.'
}
