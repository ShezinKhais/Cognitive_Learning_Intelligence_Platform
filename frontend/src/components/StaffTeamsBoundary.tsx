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
 *
 * Failure to initialize Teams host context must not remove access to an
 * otherwise-authorized C.L.I.P staff workspace. In that case the workspace
 * falls back to standalone behavior.
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

  const host =
    teams.status === 'error'
      ? 'standalone'
      : teams.host

  return (
    <div
      data-clip-user-role={user.role}
      data-teams-host={host}
    >
      {children}
    </div>
  )
}

function StaffHostStatus({
  title,
  message,
}: {
  title: string
  message: string
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <section
        role="status"
        className="w-full max-w-md rounded-xl border border-border bg-card p-6"
      >
        <h1 className="text-xl font-semibold">
          {title}
        </h1>

        <p className="mt-2 text-sm text-muted-foreground">
          {message}
        </p>
      </section>
    </main>
  )
}
