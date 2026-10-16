export interface ReviewSession {
  id: string
  title: string
  course_code: string
  ended_at: string | null
}

export interface ReviewAnswer {
  id: string
  question: string
  topic: string | null
  answer: string
  is_correct: boolean | null
  label: 'mastered' | 'partial' | 'struggling' | null
  confidence: number | null
  submitted_at: string
}

export interface ReviewPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
export interface StudentReview {
  session: ReviewSession
  questions_attempted: number
  questions_missed: number
  engagement: { status: 'unavailable'; score: null; explanation: string }
  answers: ReviewAnswer[]
  total: number
  limit: number
  offset: number
}
export interface ReviewSources {
  items: {
    chunk_id: string
    material_title: string
    source_page: number | null
    text: string
    match: 'excerpt' | 'page'
  }[]
  has_more: boolean
}
