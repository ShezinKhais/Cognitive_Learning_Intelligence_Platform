import {
  ApiError,
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

function wait(milliseconds = 150): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds)
  })
}

/**
 * Phase 1 student API adapter.
 *
 * Authentication uses the real Cyber 1 endpoints. Sessions remain mocked
 * until the live-session endpoints are delivered in Phase 3, but the mock
 * already follows the frozen paginated response contract.
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
