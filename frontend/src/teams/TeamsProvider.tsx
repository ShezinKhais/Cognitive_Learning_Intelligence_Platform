import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { createTeamsHost } from './teamsClient'
import { applyTeamsTheme } from './teamsTheme'
import type {
  TeamsContext,
  TeamsHostKind,
} from './teamsTypes'

type TeamsStatus = 'initializing' | 'ready' | 'standalone' | 'error'

interface TeamsState {
  status: TeamsStatus
  host: TeamsHostKind
  context: TeamsContext | null
  error: string | null
}

const TeamsContextValue = createContext<TeamsState | null>(null)

export function TeamsProvider({ children }: { children: ReactNode }) {
  const host = useMemo(() => createTeamsHost(), [])
  const [state, setState] = useState<TeamsState>({
    status: 'initializing',
    host: host.kind,
    context: null,
    error: null,
  })

  useEffect(() => {
    let active = true
    let removeThemeHandler: () => void = () => undefined

    async function initialize(): Promise<void> {
      try {
        const context = await host.initialize()
        if (!active) return

        if (!context) {
          applyTeamsTheme('default')
          setState({
            status: 'standalone',
            host: host.kind,
            context: null,
            error: null,
          })
          return
        }

        applyTeamsTheme(context.theme)
        removeThemeHandler = host.onThemeChange((theme) => {
          applyTeamsTheme(theme)
          setState((current) => ({
            ...current,
            context: current.context
              ? { ...current.context, theme }
              : null,
          }))
        })

        setState({
          status: 'ready',
          host: host.kind,
          context,
          error: null,
        })
      } catch (caught: unknown) {
        if (!active) return

        setState({
          status: 'error',
          host: host.kind,
          context: null,
          error:
            caught instanceof Error
              ? caught.message
              : 'Microsoft Teams could not initialize.',
        })
      }
    }

    void initialize()

    return () => {
      active = false
      removeThemeHandler()
    }
  }, [host])

  return (
    <TeamsContextValue.Provider value={state}>
      {children}
    </TeamsContextValue.Provider>
  )
}

// oxlint-disable-next-line react/only-export-components
export function useTeams(): TeamsState {
  const context = useContext(TeamsContextValue)

  if (!context) {
    throw new Error('useTeams must be used inside TeamsProvider.')
  }

  return context
}
