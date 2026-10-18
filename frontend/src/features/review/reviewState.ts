import type { Question, QuestionStatus } from '../../api'

export type ReviewFilter = 'review' | 'approved' | 'staged' | 'rejected' | 'all'

export const FILTERS: readonly { key: ReviewFilter; label: string }[] = [
  { key: 'review', label: 'To review' },
  { key: 'approved', label: 'Approved' },
  { key: 'staged', label: 'Ready to send' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'all', label: 'All' },
]

const IN_FILTER: Record<Exclude<ReviewFilter, 'all'>, readonly QuestionStatus[]> = {
  review: ['draft'],
  approved: ['approved'],
  // Delivered questions were staged first; they sit with what was sent.
  staged: ['staged', 'delivered'],
  rejected: ['rejected'],
}

export function inFilter(question: Pick<Question, 'status'>, filter: ReviewFilter): boolean {
  return filter === 'all' || IN_FILTER[filter].includes(question.status)
}

export function countByFilter(questions: readonly Pick<Question, 'status'>[]): Record<ReviewFilter, number> {
  const counts: Record<ReviewFilter, number> = { review: 0, approved: 0, staged: 0, rejected: 0, all: questions.length }
  for (const question of questions) {
    for (const key of ['review', 'approved', 'staged', 'rejected'] as const) {
      if (IN_FILTER[key].includes(question.status)) counts[key] += 1
    }
  }
  return counts
}

/** Where a lecturer starts: what still needs a decision, or everything once
 * nothing does. */
export function startingFilter(questions: readonly Pick<Question, 'status'>[]): ReviewFilter {
  return questions.some((q) => q.status === 'draft') ? 'review' : 'all'
}

/** The shortcut a key press means on a focused question, if any. */
export type Shortcut = 'next' | 'previous' | 'approve' | 'reject' | 'edit' | 'stage'

export function shortcutFor(key: string): Shortcut | null {
  switch (key.toLowerCase()) {
    case 'j':
    case 'arrowdown':
      return 'next'
    case 'k':
    case 'arrowup':
      return 'previous'
    case 'a':
      return 'approve'
    case 'r':
      return 'reject'
    case 'e':
      return 'edit'
    case 's':
      return 'stage'
    default:
      return null
  }
}
