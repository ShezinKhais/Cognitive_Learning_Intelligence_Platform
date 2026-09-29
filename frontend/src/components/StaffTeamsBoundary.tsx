import type { ReactNode } from 'react'

import type { CurrentUser } from '../api'
import { useTeams } from '../teams/TeamsProvider'

type StaffTeamsBoundaryProps = {
  user: CurrentUser
  children: ReactNode
}

/**
 * Teams-aware boundary for an already-authorised C.L.I.P staff user.
 *
 * Authentication, role enforcement and consent are handled by RoleGate before
 * this component mounts. Microsoft Teams context is host information only and
 * must never grant lecturer or administrator access.
 *
 * Staff pages continue to work in the standalone browser. When the same
 * authenticated staff user opens C.L.I.P inside Microsoft Teams, the shared
 * TeamsProvider supplies the host context and theme without creating a second
 * authorization path.
 */
export default function StaffTeamsBoundary({
  user,
  children,
}: StaffTeamsBoundaryProps) {
  const teams = useTeams()

  if (teams.status === 'initializing') {
    return (
      <StaffHostStatus
        title="Connecting to Microsoft Teams"
        message="Preparing the staff workspace..."
      />
    )
  }

  if (teams.status === 'error') {
    return (
      <StaffHostStatus
        title="Microsoft Teams unavailable"
        message={
          teams.error ??
          'The Microsoft Teams context could not be initialized.'
        }
        isError
      />
    )
  }

  return (
    <div
      data-clip-user-role={user.role}
      data-teams-host={teams.host}
    >
      {children}
    </div>
  )
}

function StaffHostStatus({
  title,
  message,
  isError = false,
}: {
  title: string
  message: string
  isError?: boolean
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <section
        role={isError ? 'alert' : 'status'}
        className="w-full max-w-md rounded-xl border border-border bg-card p-6"
      >
        <h1
          className={
            isError
              ? 'text-xl font-semibold text-critical'
              : 'text-xl font-semibold'
          }
        >
          {title}
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          {message}
        </p>
      </section>
    </main>
  )
}
