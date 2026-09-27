import type { ReactNode } from 'react'

import type { CurrentUser } from '../api'

type StaffTeamsBoundaryProps = {
  user: CurrentUser
  children: ReactNode
}

/**
 * Teams-specific boundary for an already-authorised C.L.I.P staff user.
 *
 * Authentication, role enforcement and consent are deliberately handled by
 * RoleGate before this component mounts. Teams identity or meeting context
 * must never be used here to grant lecturer or administrator access.
 *
 * The verified C.L.I.P user is accepted now so this boundary has the
 * authoritative identity available when the Teams host/context integration
 * is connected.
 */
export default function StaffTeamsBoundary({
  user: _user,
  children,
}: StaffTeamsBoundaryProps) {
  return <>{children}</>
}