import { app } from '@microsoft/teams-js'

import {
  normalizeTeamsContext,
  normalizeTheme,
  simulatedTeamsContext,
} from './teamsContext'
import type {
  TeamsContext,
  TeamsHost,
  TeamsTheme,
} from './teamsTypes'

class MicrosoftTeamsHost implements TeamsHost {
  readonly kind = 'teams' as const

  async initialize(): Promise<TeamsContext> {
    await app.initialize()
    const context = normalizeTeamsContext(await app.getContext())
    app.notifyAppLoaded()
    await app.notifySuccess()
    return context
  }

  onThemeChange(handler: (theme: TeamsTheme) => void): () => void {
    app.registerOnThemeChangeHandler((theme) => {
      handler(normalizeTheme(theme))
    })

    // TeamsJS supports one handler but does not expose an unregister method.
    // Replacing it with a no-op prevents updates after this provider unmounts.
    return () => app.registerOnThemeChangeHandler(() => undefined)
  }
}

class SimulatedTeamsHost implements TeamsHost {
  readonly kind = 'simulated' as const
  private readonly search: string

  constructor(search: string) {
    this.search = search
  }

  async initialize(): Promise<TeamsContext> {
    return simulatedTeamsContext(this.search)
  }

  onThemeChange(): () => void {
    return () => undefined
  }
}

class StandaloneHost implements TeamsHost {
  readonly kind = 'standalone' as const

  async initialize(): Promise<null> {
    return null
  }

  onThemeChange(): () => void {
    return () => undefined
  }
}

export function createTeamsHost(
  currentWindow: Window = window,
): TeamsHost {
  const query = new URLSearchParams(currentWindow.location.search)

  if (
    import.meta.env.VITE_TEAMS_MOCK_ENABLED === 'true' &&
    query.get('teamsMock') === '1'
  ) {
    return new SimulatedTeamsHost(currentWindow.location.search)
  }

  if (currentWindow.self !== currentWindow.top) {
    return new MicrosoftTeamsHost()
  }

  return new StandaloneHost()
}
