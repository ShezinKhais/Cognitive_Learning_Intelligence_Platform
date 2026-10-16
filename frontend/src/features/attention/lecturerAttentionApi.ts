import {
  apiAuthenticatedGet,
} from '../../api'

import type {
  LecturerEngagement,
} from './lecturerAttention'

export function getSessionEngagement(
  sessionId: string,
): Promise<LecturerEngagement[]> {
  return apiAuthenticatedGet<
    LecturerEngagement[]
  >(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/engagement`,
  )
}