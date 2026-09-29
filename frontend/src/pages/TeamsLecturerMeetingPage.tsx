import { Navigate } from 'react-router'

/**
 * Resolves the lecturer's Microsoft Teams meeting surface to the existing
 * C.L.I.P lecturer workspace.
 *
 * Microsoft Teams meeting context is deliberately not used to decide whether
 * the user is a lecturer. The route that mounts this component must first
 * authenticate the user and enforce the lecturer/admin role through C.L.I.P.
 *
 * The optional sessionId is only a routing hint. LecturerLiveSessionPage
 * remains the existing staff session workspace rather than duplicating the
 * dashboard for Teams.
 */
export default function TeamsLecturerMeetingPage() {
  const sessionId = new URLSearchParams(
    window.location.search,
  ).get('sessionId')

  if (!sessionId) {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
        <section
          role="status"
          className="w-full max-w-md rounded-xl border border-border bg-card p-6"
        >
          <h1 className="text-xl font-semibold">
            Lecturer meeting session unavailable
          </h1>

          <p className="mt-2 text-sm text-muted-foreground">
            C.L.I.P could not determine which lecturer session should be
            opened from this Teams meeting.
          </p>
        </section>
      </main>
    )
  }

  return (
    <Navigate
      to={`/lecturer/sessions/${encodeURIComponent(sessionId)}/live`}
      replace
    />
  )
}