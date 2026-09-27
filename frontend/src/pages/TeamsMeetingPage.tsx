import { useStudentApp } from '../features/student/StudentAppContext'
import { useTeams } from '../teams/TeamsProvider'
import { LiveSessionPanel } from './StudentLiveSessionPage'

export default function TeamsMeetingPage() {
  const teams = useTeams()
  const { sessions } = useStudentApp()
  const requestedSessionId = new URLSearchParams(window.location.search).get('sessionId')

  if (teams.status === 'initializing') {
    return <PanelStatus title="Connecting to Microsoft Teams" />
  }

  if (teams.status === 'error') {
    return (
      <PanelStatus
        title="Microsoft Teams unavailable"
        message={teams.error ?? 'The Teams context could not be loaded.'}
        isError
      />
    )
  }

  if (!teams.context && !requestedSessionId) {
    return (
      <PanelStatus
        title="Open this page in Teams"
        message="For local testing, add ?teamsMock=1&meetingId=YOUR_MEETING_ID to the URL."
      />
    )
  }

  if (teams.context && teams.context.frameContext !== 'sidePanel') {
    return (
      <PanelStatus
        title="Open the in-meeting panel"
        message="This student experience is designed for the Microsoft Teams meeting side panel."
      />
    )
  }

  const session = sessions.find(
    (candidate) =>
      (
        requestedSessionId &&
        candidate.id === requestedSessionId
      ) || (
        teams.context?.meetingId &&
        candidate.teams_meeting_id === teams.context.meetingId
      ),
  )

  if (!session) {
    return (
      <PanelStatus
        title="C.L.I.P session not found"
        message="This Teams meeting is not linked to a session assigned to your account."
        isError
      />
    )
  }

  return <LiveSessionPanel session={session} compact />
}

function PanelStatus({
  title,
  message,
  isError = false,
}: {
  title: string
  message?: string
  isError?: boolean
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-4">
      <section
        role={isError ? 'alert' : 'status'}
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5"
      >
        <h1 className={`text-lg font-semibold ${isError ? 'text-critical' : ''}`}>
          {title}
        </h1>
        {message && (
          <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        )}
      </section>
    </main>
  )
}
