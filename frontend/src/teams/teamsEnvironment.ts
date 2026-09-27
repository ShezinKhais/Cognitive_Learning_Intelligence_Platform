export type TeamsEnvironment = 'development' | 'production'

export type TeamsEnvironmentConfig = {
  production: boolean
  mockEnabled: boolean
  mockRequested: boolean
}

export function getTeamsEnvironment(
  production = import.meta.env.PROD,
): TeamsEnvironment {
  return production ? 'production' : 'development'
}

/**
 * Simulated Teams context is strictly a development/demo facility.
 *
 * A simulated Teams host is permitted only when:
 * - the build is not production;
 * - VITE_TEAMS_MOCK_ENABLED is explicitly enabled; and
 * - the current request explicitly asks for Teams simulation.
 *
 * Production always wins over the other settings. An accidentally enabled
 * environment flag or a crafted teamsMock query parameter therefore cannot
 * enable simulated Teams in a production build.
 */
export function isTeamsMockAllowed(
  config: TeamsEnvironmentConfig = {
    production: import.meta.env.PROD,
    mockEnabled: import.meta.env.VITE_TEAMS_MOCK_ENABLED === 'true',
    mockRequested:
      new URLSearchParams(window.location.search).get('teamsMock') === '1',
  },
): boolean {
  return (
    !config.production &&
    config.mockEnabled &&
    config.mockRequested
  )
}
