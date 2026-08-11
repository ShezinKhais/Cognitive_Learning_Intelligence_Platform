import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
} from 'react'

import {
  mockStudentApi,
  type StudentApi,
} from './studentApi'
import type {
  StudentSession,
  StudentUser,
} from './types'

type AuthStatus =
  | 'checking'
  | 'authenticated'
  | 'unauthenticated'
  | 'error'

interface StudentAppState {
  authStatus: AuthStatus
  currentUser: StudentUser | null
  sessions: StudentSession[]
  selectedSessionId: string | null
  error: string | null
}

type StudentAppAction =
  | {
      type: 'loaded'
      currentUser: StudentUser | null
      sessions: StudentSession[]
    }
  | {
      type: 'failed'
      message: string
    }
  | {
      type: 'session-selected'
      sessionId: string
    }

interface StudentAppContextValue extends StudentAppState {
  selectSession: (sessionId: string) => void
}

const initialState: StudentAppState = {
  authStatus: 'checking',
  currentUser: null,
  sessions: [],
  selectedSessionId: null,
  error: null,
}

const StudentAppContext =
  createContext<StudentAppContextValue | null>(null)

function reducer(
  state: StudentAppState,
  action: StudentAppAction,
): StudentAppState {
  switch (action.type) {
    case 'loaded':
      return {
        ...state,
        authStatus: action.currentUser
          ? 'authenticated'
          : 'unauthenticated',
        currentUser: action.currentUser,
        sessions: action.sessions,
        error: null,
      }

    case 'failed':
      return {
        ...state,
        authStatus: 'error',
        error: action.message,
      }

    case 'session-selected':
      return {
        ...state,
        selectedSessionId: action.sessionId,
      }
  }
}

export function StudentAppProvider({
  children,
  api = mockStudentApi,
}: {
  children: ReactNode
  api?: StudentApi
}) {
  const [state, dispatch] = useReducer(
    reducer,
    initialState,
  )

  useEffect(() => {
    let cancelled = false

    Promise.all([
      api.getCurrentStudent(),
      api.listSessions(),
    ])
      .then(([currentUser, sessions]) => {
        if (!cancelled) {
          dispatch({
            type: 'loaded',
            currentUser,
            sessions,
          })
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          dispatch({
            type: 'failed',
            message:
              caught instanceof Error
                ? caught.message
                : 'Could not load the student workspace.',
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [api])

  function selectSession(sessionId: string): void {
    dispatch({
      type: 'session-selected',
      sessionId,
    })
  }

  return (
    <StudentAppContext.Provider
      value={{
        ...state,
        selectSession,
      }}
    >
      {children}
    </StudentAppContext.Provider>
  )
}

// The provider and its hook intentionally share one context module.
// oxlint-disable-next-line react/only-export-components
export function useStudentApp(): StudentAppContextValue {
  const context = useContext(StudentAppContext)

  if (!context) {
    throw new Error(
      'useStudentApp must be used inside StudentAppProvider.',
    )
  }

  return context
}
