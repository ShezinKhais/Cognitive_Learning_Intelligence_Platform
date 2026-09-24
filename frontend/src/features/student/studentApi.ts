import {
  ApiError,
  apiAuthenticatedGet,
  getAccessToken,
  getCurrentUser,
} from '../../api'

import type {
  StudentSessionPage,
  StudentUser,
} from './types'

export interface StudentApi {
  getCurrentStudent(): Promise<StudentUser | null>
  listSessions(): Promise<StudentSessionPage>
}

export const LIVE_SESSIONS_ENABLED =
  import.meta.env.VITE_LIVE_SESSIONS_ENABLED === 'true'

/**
 * Student workspace API adapter.
 *
 * Authentication uses the real Cyber 1 endpoints. The Phase 3 session query
 * is feature-gated until BBIS deploys the frozen GET /sessions contract. An
 * unavailable integration returns an empty page rather than exposing a fake
 * session in the authenticated student workspace.
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

    return {
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    }
  },
}
