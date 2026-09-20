import {
  ApiError,
  apiAuthenticatedGet,
  apiUrl,
  clearAccessToken,
  getAccessToken,
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

async function errorFromResponse(
  response: Response,
): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `HTTP ${response.status}`

  try {
    const body =
      await response.json()

    code =
      body?.error?.code ??
      code

    message =
      body?.error?.message ??
      message
  } catch {
    // Keep the HTTP fallback if the
    // response is not the API error
    // envelope.
  }

  return new ApiError(
    response.status,
    code,
    message,
  )
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

export async function deliverQuestion(
  sessionId: string,
  questionId: string,
): Promise<DeliverQuestionResponse> {
  const token =
    getAccessToken()

  if (!token) {
    throw new ApiError(
      401,
      'UNAUTHENTICATED',
      'Login is required.',
    )
  }

  const response =
    await fetch(
      apiUrl(
        `/sessions/${encodeURIComponent(
          sessionId,
        )}/questions/${encodeURIComponent(
          questionId,
        )}:deliver`,
      ),
      {
        method: 'POST',
        headers: {
          Authorization:
            `Bearer ${token}`,
        },
      },
    )

  if (!response.ok) {
    const error =
      await errorFromResponse(
        response,
      )

    if (
      response.status === 401
    ) {
      clearAccessToken()
    }

    throw error
  }

  return response.json() as Promise<DeliverQuestionResponse>
}