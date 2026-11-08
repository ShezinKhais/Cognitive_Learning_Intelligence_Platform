import type { SessionSummary } from '../sessions/sessionsApi'

// Sessions a lecturer can put in a meeting: not finished, and not already
// held by another meeting. Soonest first, unscheduled last.
export function linkableSessions(sessions: SessionSummary[]): SessionSummary[] {
  const time = (session: SessionSummary) =>
    session.starts_at ? Date.parse(session.starts_at) : Number.POSITIVE_INFINITY
  return sessions
    .filter((session) => (session.status === 'prepared' || session.status === 'active') && !session.teams_meeting_id)
    .sort((a, b) => time(a) - time(b))
}
