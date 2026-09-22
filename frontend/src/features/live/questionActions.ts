import {
  apiAuthenticatedGet,
  apiAuthenticatedRequest,
  listQuestions,
  type Page,
} from '../../api'
import type {
  Material,
} from '../materials/types'

const MATERIAL_LIMIT = 100
const QUESTION_LIMIT = 100

export interface StagedQuestion {
  id: string
  materialId: string
  materialName: string
  prompt: string
  options: string[] | null
  sourceSlide: number | null
}

export interface DeliverQuestionResponse {
  status: 'delivered'
  question_id: string
}

export async function loadStagedQuestions():
Promise<StagedQuestion[]> {
  const materials =
    await apiAuthenticatedGet<
      Page<Material>
    >(
      `/materials?limit=${MATERIAL_LIMIT}&offset=0`,
    )

  const questionPages =
    await Promise.all(
      materials.items.map(
        async (material) => ({
          material,
          questions:
            await listQuestions(
              material.id,
              QUESTION_LIMIT,
              0,
            ),
        }),
      ),
    )

  return questionPages.flatMap(
    ({
      material,
      questions,
    }) =>
      questions.items
        .filter(
          (question) =>
            question.status ===
            'staged',
        )
        .map(
          (question) => ({
            id: question.id,
            materialId:
              material.id,
            materialName:
              material.filename,
            prompt:
              question.prompt,
            options:
              question.options,
            sourceSlide:
              question.source_slide,
          }),
        ),
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
