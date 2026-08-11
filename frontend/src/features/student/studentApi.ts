import type {
  StudentSession,
  StudentUser,
} from './types'

export interface StudentApi {
  getCurrentStudent(): Promise<StudentUser | null>
  listSessions(): Promise<StudentSession[]>
}

const demoStudent: StudentUser = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'student@example.com',
  full_name: 'Demo Student',
  role: 'student',
  consents: ['terms'],
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

export const mockStudentApi: StudentApi = {
  async getCurrentStudent() {
    await wait()

    return {
      ...demoStudent,
      consents: [...demoStudent.consents],
    }
  },

  async listSessions() {
    await wait()

    return demoSessions.map((session) => ({
      ...session,
    }))
  },
}
