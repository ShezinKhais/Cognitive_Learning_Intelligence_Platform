import { Navigate, Outlet } from 'react-router'

import RoleGate from '../components/RoleGate'

/**
 * Shared Microsoft Teams meeting entry boundary.
 *
 * C.L.I.P authentication, consent and RBAC are authoritative. Microsoft Teams
 * context may identify a meeting or provide routing context, but it must never
 * grant a student, lecturer or administrator role.
 */
export default function TeamsMeetingEntryPage() {
  return (
    <RoleGate allow={['student', 'lecturer', 'admin']}>
      {(user) => {
        if (user.role === 'student') {
          return <Outlet />
        }

        return (
          <Navigate
            to={{
              pathname: '/lecturer/teams/meeting',
              search: window.location.search,
            }}
            replace
          />
        )
      }}
    </RoleGate>
  )
}