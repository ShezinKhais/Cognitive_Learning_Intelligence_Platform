import {
  ApiError,
  apiAuthenticatedGet,
  getAccessToken,
  getCurrentUser,
} from '../../api'

import type {
  StudentSession,
  StudentSessionPage,
  StudentUser,
} from './types'

export interface StudentApi {
  getCurrentStudent(): Promise<StudentUser | null>
  listSessions(): Promise<StudentSessionPage>
}

const demoSessions: StudentSession[] = [
  {
    id: '00000000-0000-4000-8000-000000000101',
    course_code: 'CSIT321',
    title: 'Project Planning and Review',
    lecturer_id: '00000000-0000-4000-8000-000000000201',
    status: 'prepared',
    starts_at: '2026-08-15T10:00:00+04:00',
    ended_at: null,
    teams_meeting_id: null,
    participant_count: 0,
    questions_delivered: 0,
  },
]

export const LIVE_SESSIONS_ENABLED =
  import.meta.env.VITE_LIVE_SESSIONS_ENABLED === 'true'

function wait(milliseconds = 150): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds)
  })
}

/**
 * Student workspace API adapter.
 *
 * Authentication uses the real Cyber 1 endpoints. The Phase 3 session query
 * is feature-gated until BBIS deploys the frozen GET /sessions contract. The
 * development fallback follows the same response shape, so AI 2's route can
 * be reviewed without claiming that a backend-owned endpoint already works.
 */
export const phaseOneStudentApi: StudentApi = {
  async getCurrentStudent() {
    if (!getAccessToken()) {
      return null
    }

    try {
      return await getCurrentUser()
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return null
      }

      throw error
    }
  },

  async listSessions() {
    if (LIVE_SESSIONS_ENABLED) {
      return apiAuthenticatedGet<StudentSessionPage>('/sessions')
    }

    await wait()

    return {
      items: demoSessions.map((session) => ({
        ...session,
      })),
      total: demoSessions.length,
      limit: 50,
      offset: 0,
    }
  },
}
