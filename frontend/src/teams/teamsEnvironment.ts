export type TeamsEnvironment = 'development' | 'production'

export type TeamsEnvironmentConfig = {
  production: boolean
  mockEnabled: boolean
}

export function getTeamsEnvironment(
  production = import.meta.env.PROD,
): TeamsEnvironment {
  return production ? 'production' : 'development'
}

/**
 * Simulated Teams context is strictly a development/demo facility.
 *
 * Production always wins over the mock flag. This means an accidentally
 * enabled VITE_TEAMS_MOCK_ENABLED value cannot enable simulated Teams in a
 * production build.
 */
export function isTeamsMockAllowed(
  config: TeamsEnvironmentConfig = {
    production: import.meta.env.PROD,
    mockEnabled: import.meta.env.VITE_TEAMS_MOCK_ENABLED === 'true',
  },
): boolean {
  return !config.production && config.mockEnabled
}