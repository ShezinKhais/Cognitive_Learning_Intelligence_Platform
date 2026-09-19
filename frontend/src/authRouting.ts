import type { CurrentUser, Role } from './api'

// Where each role lands after sign-in and consent, and which requested pages
// it may be returned to. The review page lives at /materials/:id/review, so a
// lecturer following a review link from before sign-in arrives back on it.
const ROLE_PAGES: Record<Role, { home: string; returnable: readonly string[] }> = {
  student: { home: '/student', returnable: ['/student'] },
  lecturer: { home: '/lecturer/materials', returnable: ['/lecturer', '/materials/'] },
  admin: { home: '/admin', returnable: ['/admin'] },
}

export function defaultPathForRole(role: Role): string {
  // The role comes from the API, so a value this build does not know is
  // possible at runtime even though the type rules it out.
  return ROLE_PAGES[role]?.home ?? '/access-denied'
}

export function intendedPathForRole(
  role: Role,
  requestedPath?: string,
): string {
  const pages = ROLE_PAGES[role]
  if (pages && requestedPath && pages.returnable.some((prefix) => requestedPath.startsWith(prefix))) {
    return requestedPath
  }
  return defaultPathForRole(role)
}

export function hasRequiredConsent(user: CurrentUser): boolean {
  return user.consents.includes('terms')
}

export type AccessDecision = 'allowed' | 'wrong-role' | 'needs-consent'

// The one access rule for a signed-in user, shared by every page guard so a
// change to it cannot reach one role's pages and miss another's.
export function accessFor(user: CurrentUser, allow: readonly Role[]): AccessDecision {
  if (!allow.includes(user.role)) return 'wrong-role'
  if (!hasRequiredConsent(user)) return 'needs-consent'
  return 'allowed'
}
