import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, Bell, CheckCircle2, FileCheck2, Radio } from 'lucide-react'
import { Link } from 'react-router'

import type { CurrentUser } from '../../api'
import { listMaterials } from '../materials/materialApi'
import { listSessions } from '../sessions/sessionsApi'
import { buildNotifications, unreadCount, type AppNotification, type NotificationKind } from './notifications'

const REFRESH_MS = 60_000

const ICON: Record<NotificationKind, typeof Bell> = {
  live: Radio,
  ready: FileCheck2,
  results: CheckCircle2,
  problem: AlertTriangle,
}

function readKey(user: CurrentUser): string {
  return `clip_read_notifications_${user.id}`
}

function loadRead(user: CurrentUser): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(readKey(user)) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

async function readinessDown(): Promise<string[]> {
  try {
    const body = (await (await fetch('/api/v1/ready')).json()) as { dependencies?: { name: string; ok: boolean }[] }
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
        listSessions().then((page) => page.items, () => []),
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
  const items = useNotifications(user)
  const [read, setRead] = useState(() => loadRead(user))
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const unread = unreadCount(items, read)

  const markAllRead = useCallback(() => {
    const next = new Set([...read, ...items.map((item) => item.id)])
    setRead(next)
    try {
      window.localStorage.setItem(readKey(user), JSON.stringify([...next].slice(-200)))
    } catch {
      // Storage blocked: they come back as unread next visit.
    }
  }, [items, read, user])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((value) => !value)
          if (!open) markAllRead()
        }}
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
              {unread}
            </motion.span>
          )}
        </AnimatePresence>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Notifications"
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.16 }}
            className="absolute bottom-full left-0 z-40 mb-2 w-80 overflow-hidden rounded-lg border border-border bg-popover shadow-[var(--shadow-card-hover)] lg:bottom-0 lg:left-full lg:mb-0 lg:ml-2"
          >
            <p className="border-b border-border px-4 py-2.5 font-semibold">Notifications</p>
            {items.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">Nothing new. You are up to date.</p>
            ) : (
              <ul className="max-h-96 divide-y divide-border overflow-auto">
                {items.map((item) => {
                  const Icon = ICON[item.kind]
                  return (
                    <li key={item.id}>
                      <Link to={item.to} onClick={() => setOpen(false)} className="flex gap-3 px-4 py-3 transition-colors hover:bg-muted">
                        <Icon size={17} aria-hidden className={item.kind === 'problem' ? 'mt-0.5 text-critical' : item.kind === 'live' ? 'mt-0.5 text-primary' : 'mt-0.5 text-success'} />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold">{item.title}</span>
                          <span className="block text-sm text-muted-foreground">{item.detail}</span>
                          <span className="mt-1 block text-sm font-semibold text-primary">{item.action}</span>
                        </span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
