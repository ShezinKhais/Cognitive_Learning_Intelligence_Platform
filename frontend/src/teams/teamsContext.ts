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
    mobile: isMobileClient(context.app.host?.clientType),
  }
}

const MOBILE_CLIENTS = new Set(['android', 'ios', 'ipados'])

/** Teams on a phone shows a tab full screen, not framed by Teams, so being
 * framed cannot tell it apart from a browser. Its web view says so instead:
 * the user agent ends TeamsMobile-Android or TeamsMobile-iOS. */
export function isTeamsMobileAgent(userAgent: string): boolean {
  return /\bTeamsMobile-(Android|iOS)\b/i.test(userAgent)
}

export function isMobileClient(clientType: unknown): boolean {
  return typeof clientType === 'string' && MOBILE_CLIENTS.has(clientType.toLowerCase())
}

// Where a simulated meeting shows C.L.I.P: the side panel (the default), or
// the stage a lecturer shared it to ('content'), or a notification dialog.
const SIMULATED_FRAMES = new Set(['sidePanel', 'content', 'task'])

export function simulatedTeamsContext(search: string): TeamsContext {
  const query = new URLSearchParams(search)
  const frame = query.get('frame')

  return {
    meetingId: query.get('meetingId'),
    userId: query.get('userId') ?? 'simulated-student',
    tenantId: query.get('tenantId') ?? 'simulated-tenant',
    displayName: query.get('displayName') ?? 'Simulated student',
    loginHint: query.get('loginHint') ?? 'student@example.test',
    locale: query.get('locale') ?? 'en-us',
    theme: normalizeTheme(query.get('theme')),
    frameContext: frame && SIMULATED_FRAMES.has(frame) ? frame : 'sidePanel',
    mobile: query.get('mobile') === '1',
  }
}
