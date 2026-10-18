import { Link } from 'react-router'

import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'
import { problemArt } from '../components/ui/problem'
import { useStudentApp } from '../features/student/StudentAppContext'
import { LIVE_SESSIONS_ENABLED } from '../features/student/studentApi'
import type { StudentSession } from '../features/student/types'
import { formatWhen, groupSessions, statusLabel, statusTone } from '../features/sessions/format'

export default function StudentHomePage() {
  const { authStatus, currentUser, sessions, error, cause } = useStudentApp()

  if (authStatus === 'checking') {
    return <MessagePanel title="Loading your sessions" message="Checking your account and sessions…" />
  }
  if (authStatus === 'error') {
    return (
      <PageBody>
        <ProblemState art={problemArt(cause)} title="Your sessions could not be loaded">
          {error ?? 'An unexpected error occurred.'}
        </ProblemState>
      </PageBody>
    )
  }
  if (authStatus === 'unauthenticated' || !currentUser) {
    return <MessagePanel title="Sign in required" message="Sign in before opening your sessions." />
  }
  if (currentUser.role !== 'student') {
    return <MessagePanel title="Student access required" message="This page is only for student accounts." isError />
  }

  const groups = groupSessions(sessions.map((session) => ({ ...session, paused: session.paused ?? false })))
  const firstName = currentUser.full_name.split(' ')[0]

  return (
    <>
      <PageHeader
        title={`Hello, ${firstName}`}
        description="Join a class when it goes live, and look back at the ones you have finished."
      />
      <PageBody>
        {!LIVE_SESSIONS_ENABLED && (
          <p role="status" className="mb-6 rounded-md border border-info/30 bg-info/5 px-4 py-3 text-sm">
            Live sessions are switched off in this build, so none are listed.
          </p>
        )}

        {sessions.length === 0 && (
          <EmptyState art="lecture" title="No sessions yet">
            Sessions for your courses appear here as soon as your lecturer prepares them.
          </EmptyState>
        )}

        {groups.live.length > 0 && <Group heading="Live now" sessions={groups.live} />}
        {groups.prepared.length > 0 && <Group heading="Coming up" sessions={groups.prepared} />}
        {groups.finished.length > 0 && <Group heading="Finished" sessions={groups.finished} />}

        {!LIVE_SESSIONS_ENABLED && (
          <Link to="/student/reviews" className={buttonStyles({ intent: 'secondary' })}>
            Go over past sessions
          </Link>
        )}
      </PageBody>
    </>
  )
}

function Group({ heading, sessions }: { heading: string; sessions: (StudentSession & { paused: boolean })[] }) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-lg font-bold">{heading}</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {sessions.map((session) => (
          <li key={session.id}>
            <SessionCard session={session} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function SessionCard({ session }: { session: StudentSession & { paused: boolean } }) {
  const finished = session.status === 'ended'
  const joinable = session.status === 'prepared' || session.status === 'active'
  return (
    <article className="flex h-full flex-col rounded-lg border border-border bg-card px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-muted-foreground">{session.course_code}</span>
        <Tag tone={statusTone(session)}>{statusLabel(session)}</Tag>
      </div>
      <h3 className="mt-2 text-[1.05rem] font-bold">{session.title}</h3>
      <p className="mt-0.5 text-sm text-muted-foreground">{formatWhen(session.ended_at ?? session.starts_at)}</p>
      <div className="mt-auto pt-4">
        {joinable && (
          <Link
            to={`/student/session/${session.id}`}
            className={buttonStyles({ intent: session.status === 'active' ? 'primary' : 'secondary' })}
          >
            {session.status === 'active' ? 'Join the class' : 'Open the waiting room'}
          </Link>
        )}
        {finished && (
          <span className="flex flex-wrap gap-2">
            <Link to={`/student/session/${session.id}/summary`} className={buttonStyles({ intent: 'secondary' })}>
              See how you did
            </Link>
            <Link to={`/student/reviews/${session.id}`} className={buttonStyles({ intent: 'quiet' })}>
              Your answers
            </Link>
          </span>
        )}
      </div>
    </article>
  )
}

function MessagePanel({ title, message, isError = false }: { title: string; message: string; isError?: boolean }) {
  return (
    <PageBody>
      <div role={isError ? 'alert' : 'status'} className="max-w-md rounded-lg border border-border bg-card p-6">
        <h1 className={isError ? 'text-xl font-bold text-critical' : 'text-xl font-bold'}>{title}</h1>
        <p className="mt-2 text-muted-foreground">{message}</p>
      </div>
    </PageBody>
  )
}
