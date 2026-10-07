import {
  apiAuthenticatedGet,
} from '../../api'

import type {
  TopicDifficulty,
} from './topicRecovery'

export function getSessionTopics(
  sessionId: string,
): Promise<TopicDifficulty[]> {
  return apiAuthenticatedGet<TopicDifficulty[]>(
    `/sessions/${encodeURIComponent(
      sessionId,
    )}/topics`,
  )
}