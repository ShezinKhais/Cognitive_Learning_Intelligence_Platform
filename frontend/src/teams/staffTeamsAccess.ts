export type ClipStaffRole = 'student' | 'lecturer' | 'admin'

export type StaffTeamsAccessInput = {
  clipRole: ClipStaffRole
  hasConsent: boolean
}

/**
 * Teams identity and meeting context are intentionally absent from this
 * decision. They may describe where C.L.I.P is running, but they must never
 * grant lecturer or administrator access.
 *
 * C.L.I.P authentication, consent and RBAC remain authoritative.
 */
export function canAccessStaffTeamsSurface({
  clipRole,
  hasConsent,
}: StaffTeamsAccessInput): boolean {
  return hasConsent && (clipRole === 'lecturer' || clipRole === 'admin')
}