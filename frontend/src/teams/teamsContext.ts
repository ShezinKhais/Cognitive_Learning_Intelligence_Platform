import type { app } from '@microsoft/teams-js'

import type {
  TeamsContext,
  TeamsTheme,
} from './teamsTypes'

export function isTeamsMockAllowed(
  enabled: boolean,
  production: boolean,
): boolean {
  return enabled && !production
}

export function normalizeTheme(value: string | null | undefined): TeamsTheme {
  if (
    value === 'dark' ||
    value === 'contrast' ||
    value === 'glass'
  ) {
    return value
  }

  return 'default'
}

export function normalizeTeamsContext(context: app.Context): TeamsContext {
  return {
    meetingId: context.meeting?.id ?? null,
    userId: context.user?.id ?? null,
    tenantId: context.user?.tenant?.id ?? null,
    displayName: context.user?.displayName ?? null,
    loginHint:
      context.user?.loginHint ??
      context.user?.userPrincipalName ??
      null,
    locale: context.app.locale || 'en-us',
    theme: normalizeTheme(context.app.theme),
    frameContext: String(context.page.frameContext),
  }
}

export function simulatedTeamsContext(search: string): TeamsContext {
  const query = new URLSearchParams(search)

  return {
    meetingId: query.get('meetingId'),
    userId: query.get('userId') ?? 'simulated-student',
    tenantId: query.get('tenantId') ?? 'simulated-tenant',
    displayName: query.get('displayName') ?? 'Simulated student',
    loginHint: query.get('loginHint') ?? 'student@example.test',
    locale: query.get('locale') ?? 'en-us',
    theme: normalizeTheme(query.get('theme')),
    frameContext: 'sidePanel',
  }
}
