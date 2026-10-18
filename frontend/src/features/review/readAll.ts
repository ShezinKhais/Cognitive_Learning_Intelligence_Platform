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

/** Every finished session the student has, each with all of its answers. */
export async function allReviews(read: Read): Promise<StudentReview[]> {
  const sessions = await everyPage((offset) =>
    read<ReviewPage<ReviewSession>>(`/student-reviews?limit=${SESSIONS_PER_PAGE}&offset=${offset}`),
  )
  return Promise.all(sessions.map((session) => wholeReview(read, session.id)))
}
