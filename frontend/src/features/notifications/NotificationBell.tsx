import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, Bell, CheckCircle2, FileCheck2, Radio, X } from 'lucide-react'
import { Link } from 'react-router'

import { apiUrl, type CurrentUser } from '../../api'
import Illustration from '../../components/ui/Illustration'
import { listMaterials } from '../materials/materialApi'
import { listSessions } from '../sessions/sessionsApi'
import { LIVE_SESSIONS_ENABLED } from '../student/studentApi'
import { formatClock, formatRelative } from '../format/relativeTime'
import {
  badgeLabel,
  buildNotifications,
  groupByDay,
  remembered,
  unreadCount,
  withoutCleared,
  type AppNotification,
  type NotificationKind,
} from './notifications'

const REFRESH_MS = 60_000
const PANEL_WIDTH = 320
const GAP = 8
const EDGE = 16

/**
 * Where the panel goes, from where the bell is. The side menu scrolls, so a
 * panel positioned inside it is cut off at its edge; this one is drawn over
 * the page instead. Beside the bell on a wide screen, otherwise below it, or
 * above when there is more room there, and never past the window.
 */
function placePanel(bell: DOMRect): CSSProperties {
  const width = Math.min(PANEL_WIDTH, window.innerWidth - EDGE * 2)
  if (window.innerWidth >= 1024) {
    return {
      left: bell.right + GAP,
      bottom: Math.max(EDGE, window.innerHeight - bell.bottom),
      width,
      maxHeight: Math.max(160, bell.bottom - EDGE),
    }
  }
  const left = Math.min(Math.max(EDGE, bell.left), window.innerWidth - width - EDGE)
  const below = window.innerHeight - bell.bottom - GAP - EDGE
  const above = bell.top - GAP - EDGE
  return below >= above
    ? { left, top: bell.bottom + GAP, width, maxHeight: below }
    : { left, bottom: window.innerHeight - bell.top + GAP, width, maxHeight: above }
}

const ICON: Record<NotificationKind, typeof Bell> = {
  live: Radio,
  ready: FileCheck2,
  results: CheckCircle2,
  problem: AlertTriangle,
}

type Kept = 'read' | 'cleared'

// Sent when one bell changes what is kept, so the other (the phone menu and
// the desktop menu each mount one) follows without waiting for a reload.
const KEPT_CHANGED = 'clip-notifications-kept'

function keptKey(user: CurrentUser, kept: Kept): string {
  return `clip_${kept}_notifications_${user.id}`
}

function loadKept(user: CurrentUser, kept: Kept): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(keptKey(user, kept)) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

/** Notification ids this user has read, or cleared, in this browser. */
function useKept(user: CurrentUser, kept: Kept): [ReadonlySet<string>, (ids: readonly string[]) => void] {
  const [ids, setIds] = useState(() => loadKept(user, kept))
  useEffect(() => {
    const reload = () => setIds(loadKept(user, kept))
    reload()
    window.addEventListener(KEPT_CHANGED, reload)
    window.addEventListener('storage', reload)
    return () => {
      window.removeEventListener(KEPT_CHANGED, reload)
      window.removeEventListener('storage', reload)
    }
  }, [user, kept])
  const add = useCallback(
    (added: readonly string[]) => {
      const next = remembered(loadKept(user, kept), added)
      setIds(new Set(next))
      try {
        window.localStorage.setItem(keptKey(user, kept), JSON.stringify(next))
      } catch {
        // Storage blocked: kept for this page only.
      }
      window.dispatchEvent(new Event(KEPT_CHANGED))
    },
    [user, kept],
  )
  return [ids, add]
}

async function readinessDown(): Promise<string[]> {
  try {
    const body = (await (await fetch(apiUrl('/ready'))).json()) as { dependencies?: { name: string; ok: boolean }[] }
    const names: Record<string, string> = { postgres: 'The database', ollama: 'The AI models' }
    return (body.dependencies ?? []).filter((d) => !d.ok).map((d) => names[d.name] ?? d.name)
  } catch {
    return []
  }
}

function useNotifications(user: CurrentUser): AppNotification[] {
  const [items, setItems] = useState<AppNotification[]>([])
  useEffect(() => {
    let cancelled = false
    async function load() {
      const [sessions, materials, down] = await Promise.all([
        user.role === 'student' && !LIVE_SESSIONS_ENABLED
          ? Promise.resolve([])
          : listSessions().then((page) => page.items, () => []),
        user.role === 'student' ? Promise.resolve([]) : listMaterials().catch(() => []),
        user.role === 'admin' ? readinessDown() : Promise.resolve([]),
      ])
      if (!cancelled) setItems(buildNotifications(user.role, { sessions, materials, down }))
    }
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [user])
  return items
}

/** The bell in the side menu, with what is new for this user. */
export default function NotificationBell({ user }: { user: CurrentUser }) {
  const [cleared, clear] = useKept(user, 'cleared')
  const items = withoutCleared(useNotifications(user), cleared)
  const [read, remember] = useKept(user, 'read')
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const bell = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<CSSProperties>({})
  const unread = unreadCount(items, read)

  const markAllRead = () => remember(items.map((item) => item.id))
  const clearAll = () => {
    const ids = items.map((item) => item.id)
    remember(ids)
    clear(ids)
  }

  useLayoutEffect(() => {
    if (!open) return
    const follow = () => {
      if (bell.current) setPlace(placePanel(bell.current.getBoundingClientRect()))
    }
    follow()
    window.addEventListener('resize', follow)
    // Capture, so the side menu scrolling moves the panel with the bell.
    window.addEventListener('scroll', follow, true)
    return () => {
      window.removeEventListener('resize', follow)
      window.removeEventListener('scroll', follow, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const frame = requestAnimationFrame(() => panel.current?.focus({ preventScroll: true }))
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key !== 'Escape') return
        setOpen(false)
        bell.current?.focus()
      } else if (
        !root.current?.contains(event.target as Node) &&
        !panel.current?.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        ref={bell}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} new` : 'Notifications'}
        className="relative flex w-full items-center gap-2 rounded-md px-3 py-2 text-[0.95rem] hover:bg-muted"
      >
        <Bell size={17} aria-hidden />
        Notifications
        <AnimatePresence>
          {unread > 0 && (
            <motion.span
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              transition={{ type: 'spring', stiffness: 500, damping: 28 }}
              className="ml-auto rounded-full bg-highlight px-1.5 text-xs font-bold text-highlight-foreground"
            >
              {badgeLabel(unread)}
            </motion.span>
          )}
        </AnimatePresence>
      </button>
      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div
              ref={panel}
              tabIndex={-1}
              role="dialog"
              aria-label="Notifications"
              initial={{ opacity: 0, y: 6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.98 }}
              transition={{ duration: 0.16 }}
              style={place}
              className="fixed z-50 flex flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-[var(--shadow-card-hover)]"
            >
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-2.5">
                <p className="font-semibold">Notifications</p>
                <span className="flex items-center gap-1">
                  {unread > 0 && (
                    <button
                      type="button"
                      onClick={markAllRead}
                      className="rounded px-1.5 py-0.5 text-sm font-semibold text-primary hover:bg-muted"
                    >
                      Mark all read
                    </button>
                  )}
                  {items.length > 0 && (
                    <button
                      type="button"
                      onClick={clearAll}
                      className="rounded px-1.5 py-0.5 text-sm font-semibold text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      Clear all
                    </button>
                  )}
                </span>
              </div>
              {items.length === 0 ? (
                <div className="px-4 py-6 text-center">
                  <Illustration name="notifications" className="mx-auto mb-3 h-20 w-28" />
                  <p className="text-sm text-muted-foreground">Nothing new. You are up to date.</p>
                  {cleared.size > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">New notifications still show up here.</p>
                  )}
                </div>
              ) : (
                <div className="max-h-96 min-h-0 overflow-auto">
                  {groupByDay(items).map((group) => (
                    <section key={group.label} aria-label={group.label}>
                      <h3 className="sticky top-0 z-10 border-b border-border bg-popover/95 px-4 py-1.5 text-xs font-semibold text-muted-foreground backdrop-blur">
                        {group.label}
                      </h3>
                      <ul className="divide-y divide-border">
                        <AnimatePresence initial={false}>
                        {group.items.map((item) => {
                          const Icon = ICON[item.kind]
                          const fresh = !read.has(item.id)
                          return (
                            <motion.li
                              key={item.id}
                              layout
                              exit={{ opacity: 0, x: 24, transition: { duration: 0.16 } }}
                              className="group relative"
                            >
                              <Link
                                to={item.to}
                                onClick={() => {
                                  remember([item.id])
                                  setOpen(false)
                                }}
                                className={`flex gap-3 py-3 pl-4 pr-10 transition-colors hover:bg-muted ${fresh ? 'bg-primary/[0.06]' : ''}`}
                              >
                                <Icon size={17} aria-hidden className={item.kind === 'problem' ? 'mt-0.5 shrink-0 text-critical' : item.kind === 'live' ? 'mt-0.5 shrink-0 text-primary' : 'mt-0.5 shrink-0 text-success'} />
                                <span className="min-w-0 flex-1">
                                  <span className="flex items-start justify-between gap-2">
                                    <span className="break-words text-sm font-semibold">{item.title}</span>
                                    <time dateTime={item.at} title={new Date(item.at).toLocaleString()} className="shrink-0 pt-px text-xs text-muted-foreground">
                                      {group.label === 'Today' ? formatRelative(item.at) : formatClock(item.at, group.label === 'Earlier this week')}
                                    </time>
                                  </span>
                                  <span className="block text-sm text-muted-foreground">{item.detail}</span>
                                  <span className="mt-1 block text-sm font-semibold text-primary">{item.action}</span>
                                </span>
                                {fresh && (
                                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary">
                                    <span className="sr-only">New</span>
                                  </span>
                                )}
                              </Link>
                              <button
                                type="button"
                                onClick={() => {
                                  remember([item.id])
                                  clear([item.id])
                                }}
                                aria-label={`Remove: ${item.title}`}
                                title="Remove"
                                className="absolute right-2 bottom-2.5 rounded-md p-1.5 text-muted-foreground opacity-60 transition-opacity hover:bg-background hover:text-foreground hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100"
                              >
                                <X size={14} aria-hidden />
                              </button>
                            </motion.li>
                          )
                        })}
                        </AnimatePresence>
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  )
}
