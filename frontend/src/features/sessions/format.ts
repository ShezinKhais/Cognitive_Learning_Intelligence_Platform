import type { Tone } from '../../components/ui/primitives'
import type { SessionStatus, SessionSummary } from './sessionsApi'

const DATE = new Intl.DateTimeFormat('en-AE', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'Asia/Dubai',
})

export function formatWhen(value: string | null | undefined, fallback = 'No start time set'): string {
  if (!value) return fallback
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? fallback : DATE.format(at)
}

export const STATUS_LABEL: Record<SessionStatus, string> = {
  prepared: 'Prepared',
  active: 'Live',
  ending: 'Ending',
  ended: 'Finished',
  cancelled: 'Cancelled',
}

export function statusTone(session: Pick<SessionSummary, 'status' | 'paused'>): Tone {
  if (session.status === 'active') return session.paused ? 'mixed' : 'live'
  if (session.status === 'ending') return 'mixed'
  if (session.status === 'prepared') return 'info'
  return 'neutral'
}

export function statusLabel(session: Pick<SessionSummary, 'status' | 'paused'>): string {
  return session.status === 'active' && session.paused ? 'Paused' : STATUS_LABEL[session.status]
}

export type SessionGroup = 'live' | 'prepared' | 'finished'

export function groupOf(status: SessionStatus): SessionGroup {
  if (status === 'active' || status === 'ending') return 'live'
  if (status === 'prepared') return 'prepared'
  return 'finished'
}

/** Sessions split into live, prepared and finished, each newest first as
 * the API returns them. */
export function groupSessions<T extends Pick<SessionSummary, 'status'>>(sessions: readonly T[]): Record<SessionGroup, T[]> {
  const groups: Record<SessionGroup, T[]> = { live: [], prepared: [], finished: [] }
  for (const session of sessions) groups[groupOf(session.status)].push(session)
  return groups
}
