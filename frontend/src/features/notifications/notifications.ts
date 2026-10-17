import type { Role } from '../../api'
import { daysBetween } from '../format/relativeTime.ts'
import type { Material } from '../materials/types'
import type { SessionSummary } from '../sessions/sessionsApi'

export type NotificationKind = 'live' | 'ready' | 'results' | 'problem'

export interface AppNotification {
  /** Stable for the same event, so a read one stays read. */
  id: string
  kind: NotificationKind
  title: string
  detail: string
  to: string
  action: string
  at: string
}

export interface NotificationSources {
  sessions?: readonly SessionSummary[]
  materials?: readonly Material[]
  /** Services /ready reports as unreachable. */
  down?: readonly string[]
  now?: number
}

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

/** What is worth telling this role about, newest first. Built only from
 * what the app already loads; nothing here is invented. */
export function buildNotifications(role: Role, sources: NotificationSources): AppNotification[] {
  const now = sources.now ?? Date.now()
  const recent = (at: string | null | undefined) => !!at && now - Date.parse(at) < WEEK_MS
  const found: AppNotification[] = []

  for (const session of sources.sessions ?? []) {
    if (session.status === 'active') {
      found.push({
        id: `live-${session.id}`,
        kind: 'live',
        title: role === 'student' ? `${session.title} is live` : `${session.title} is live now`,
        detail: session.course_code,
        to: role === 'student' ? `/student/session/${session.id}` : `/lecturer/sessions/${session.id}/live`,
        action: role === 'student' ? 'Join the class' : 'Open live view',
        at: session.starts_at ?? new Date(now).toISOString(),
      })
    } else if (session.status === 'ended' && recent(session.ended_at)) {
      found.push({
        id: `ended-${session.id}`,
        kind: 'results',
        title: role === 'student' ? `How you did in ${session.title}` : `${session.title} has finished`,
        detail: session.course_code,
        to: role === 'student' ? `/student/session/${session.id}/summary` : `/lecturer/sessions/${session.id}/report`,
        action: role === 'student' ? 'See your answers' : 'Read the report',
        at: session.ended_at!,
      })
    }
  }

  if (role !== 'student') {
    for (const material of sources.materials ?? []) {
      if (material.status === 'completed' && recent(material.uploaded_at)) {
        found.push({
          id: `ready-${material.id}`,
          kind: 'ready',
          title: `${material.filename} is ready`,
          detail: 'Its questions are waiting for your review',
          to: `/materials/${material.id}/review`,
          action: 'Review questions',
          at: material.uploaded_at,
        })
      }
    }
  }

  if (role === 'admin') {
    for (const service of sources.down ?? []) {
      found.push({
        id: `down-${service}`,
        kind: 'problem',
        title: `${service} is unreachable`,
        detail: 'Features that need it will fail until it is back',
        to: '/admin/status',
        action: 'Check status',
        at: new Date(now).toISOString(),
      })
    }
  }

  return found.sort((a, b) => Date.parse(b.at) - Date.parse(a.at)).slice(0, MAX_NOTIFICATIONS)
}

export function unreadCount(notifications: readonly AppNotification[], read: ReadonlySet<string>): number {
  return notifications.filter((item) => !read.has(item.id)).length
}

/** The most the panel lists. Older ones are still a week away from ageing
 * out, but past this many nobody reads them. */
export const MAX_NOTIFICATIONS = 30

/** The badge: a count while it is readable, then 99+. */
export function badgeLabel(count: number): string {
  return count > 99 ? '99+' : String(count)
}

export interface NotificationGroup {
  label: 'Today' | 'Yesterday' | 'Earlier this week'
  items: AppNotification[]
}

/** Newest first, split by day in the class's time zone. Empty groups are
 * left out. */
export function groupByDay(
  notifications: readonly AppNotification[],
  now = Date.now(),
): NotificationGroup[] {
  const groups: NotificationGroup[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Earlier this week', items: [] },
  ]
  for (const item of notifications) {
    const days = daysBetween(Date.parse(item.at), now)
    groups[days <= 0 ? 0 : days === 1 ? 1 : 2].items.push(item)
  }
  return groups.filter((group) => group.items.length > 0)
}
