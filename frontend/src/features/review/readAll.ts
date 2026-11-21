import type { ReviewPage, ReviewSession, StudentReview } from './reviewTypes.ts'

type Read = <T>(path: string) => Promise<T>

// The most the backend returns in one page (deps.Pagination).
const SESSIONS_PER_PAGE = 200
const ANSWERS_PER_PAGE = 200

/** Every item of a paged list, page after page until `total` is reached. */
export async function everyPage<T>(
  read: (offset: number) => Promise<{ items: T[]; total: number }>,
): Promise<T[]> {
  const items: T[] = []
  for (;;) {
    const page = await read(items.length)
    items.push(...page.items)
    // An empty page ends it too, so a total that shrinks mid-read cannot loop.
    if (items.length >= page.total || page.items.length === 0) return items
  }
}

/** One finished session with every answer in it, read across pages. */
async function wholeReview(read: Read, sessionId: string): Promise<StudentReview> {
  const path = (offset: number) =>
    `/student-reviews/${encodeURIComponent(sessionId)}?limit=${ANSWERS_PER_PAGE}&offset=${offset}`
  let first: StudentReview | undefined
  const answers = await everyPage(async (offset) => {
    const page = await read<StudentReview>(path(offset))
    first ??= page
    return { items: page.answers, total: page.total }
  })
  return { ...(first as StudentReview), answers, total: answers.length, limit: answers.length, offset: 0 }
}

export interface ReviewsLoaded {
  reviews: StudentReview[]
  unavailable: ReviewSession[]
}

/** Read review history with at most four lessons in flight. A failed lesson
 * can be retried separately from lessons already loaded. */
export async function allReviews(
  read: Read,
  retrySessions?: ReviewSession[],
  signal?: AbortSignal,
): Promise<ReviewsLoaded> {
  const sessions = retrySessions ?? await everyPage((offset) =>
    read<ReviewPage<ReviewSession>>(`/student-reviews?limit=${SESSIONS_PER_PAGE}&offset=${offset}`),
  )
  const results: ({ review: StudentReview } | { failed: ReviewSession })[] = []
  let next = 0
  async function worker() {
    while (next < sessions.length && !signal?.aborted) {
      const index = next++
      const session = sessions[index]
      try {
        results[index] = { review: await wholeReview(read, session.id) }
      } catch {
        results[index] = { failed: session }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, sessions.length) }, () => worker()))
  return {
    reviews: results.flatMap((result) => 'review' in result ? [result.review] : []),
    unavailable: results.flatMap((result) => 'failed' in result ? [result.failed] : []),
  }
}
