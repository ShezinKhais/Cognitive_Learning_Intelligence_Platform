import {
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
  type Page,
} from '../../api'

const QUESTION_PAGE_SIZE = 200

export interface StagedQuestion {
  id: string
  materialId: string
  prompt: string
  options: string[] | null
  sourceSlide: number | null
}

interface DeliverableQuestionResponse {
  id: string
  material_id: string
  prompt: string
  options: string[] | null
  source_slide: number | null
}

export interface DeliverQuestionResponse {
  status: 'delivered'
  question_id: string
}

export async function loadStagedQuestions(
  sessionId: string,
): Promise<StagedQuestion[]> {
  const questions: DeliverableQuestionResponse[] = []
  let offset = 0
  let total = 0

  do {
    const page =
      await apiAuthenticatedGet<
        Page<DeliverableQuestionResponse>
      >(
        `/sessions/${encodeURIComponent(
          sessionId,
        )}/questions?limit=${QUESTION_PAGE_SIZE}&offset=${offset}`,
      )

    questions.push(...page.items)
    total = page.total

    if (page.items.length === 0) {
      break
    }

    offset += page.items.length
  } while (questions.length < total)

  return questions.map(
    (question) => ({
      id: question.id,
      materialId:
        question.material_id,
      prompt:
        question.prompt,
      options:
        question.options,
      sourceSlide:
        question.source_slide,
    }),
  )
}

export function deliverQuestion(
  sessionId: string,
  questionId: string,
): Promise<DeliverQuestionResponse> {
  return apiAuthenticatedRequest<DeliverQuestionResponse>(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/questions/${encodeURIComponent(
      questionId,
    )}:deliver`,
    {
      method: 'POST',
    },
  )
}
