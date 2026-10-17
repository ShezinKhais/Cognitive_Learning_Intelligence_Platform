import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CornerDownLeft, LogOut, Monitor, Moon, Search, Sun, type LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router'

import { clearAccessToken, type CurrentUser } from '../../api'
import { cn } from '../ui/cn'
import { NAVIGATION } from './navigation'
import { saveTheme } from './theme'

interface Entry {
  id: string
  label: string
  hint: string
  icon: LucideIcon
  run: () => void
}

/**
 * Type a few letters of where you want to go and press Enter. A combobox over
 * a listbox, so arrow keys move, Enter chooses and Escape closes, and focus
 * goes back to whatever opened it.
 */
export default function QuickJump({ user, open, onClose }: { user: CurrentUser; open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const returnTo = useRef<HTMLElement | null>(null)
  const listId = useId()

  const entries = useMemo<Entry[]>(() => {
    const go = (to: string) => () => navigate(to)
    const pages = (NAVIGATION[user.role] ?? []).map((item) => ({
      id: item.to,
      label: item.label,
      hint: item.planned ? 'Planned' : 'Page',
      icon: item.icon,
      run: go(item.to),
    }))
    return [
      ...pages,
      { id: 'theme-light', label: 'Light theme', hint: 'Theme', icon: Sun, run: () => saveTheme('light') },
      { id: 'theme-dark', label: 'Dark theme', hint: 'Theme', icon: Moon, run: () => saveTheme('dark') },
      { id: 'theme-system', label: 'Match device theme', hint: 'Theme', icon: Monitor, run: () => saveTheme('system') },
      {
        id: 'sign-out',
        label: 'Sign out',
        hint: 'Account',
        icon: LogOut,
        run: () => {
          clearAccessToken()
          window.location.assign('/login')
        },
      },
    ]
  }, [navigate, user.role])

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return entries.filter((entry) => words.every((word) => `${entry.label} ${entry.hint}`.toLowerCase().includes(word)))
  }, [entries, query])

  useEffect(() => {
    if (!open) return
    returnTo.current = document.activeElement as HTMLElement | null
    setQuery('')
    setActive(0)
    // After the dialog has painted.
    const frame = requestAnimationFrame(() => input.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      returnTo.current?.focus?.()
    }
  }, [open])

  useEffect(() => setActive(0), [query])

  // Keep the highlighted option in view as the arrow keys move it.
  useEffect(() => {
    if (!open) return
    document.getElementById(`${listId}-${shown[active]?.id}`)?.scrollIntoView({ block: 'nearest' })
  }, [active, open, listId, shown])

  function choose(entry: Entry | undefined) {
    if (!entry) return
    onClose()
    entry.run()
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => (shown.length ? (index + 1) % shown.length : 0))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => (shown.length ? (index - 1 + shown.length) % shown.length : 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(shown[active])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    } else if (event.key === 'Tab') {
      // Nothing else in here takes focus.
      event.preventDefault()
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/25 px-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          transition={{ duration: 0.15 }}
          onMouseDown={(event) => event.target === event.currentTarget && onClose()}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Go to"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.99, transition: { duration: 0.12 } }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="w-full max-w-lg overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-[0_24px_64px_-12px_rgba(27,28,43,0.35)]"
            onKeyDown={onKeyDown}
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search size={17} aria-hidden className="shrink-0 text-muted-foreground" />
              <input
                ref={input}
                role="combobox"
                aria-expanded="true"
                aria-controls={listId}
                aria-activedescendant={shown[active] ? `${listId}-${shown[active].id}` : undefined}
                aria-autocomplete="list"
                aria-label="Go to a page or run a command"
                placeholder="Go to…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
              />
              <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground sm:block">Esc</kbd>
            </div>
            <ul id={listId} role="listbox" aria-label="Results" className="max-h-[min(24rem,60vh)] overflow-y-auto p-1.5">
              {shown.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing matches "{query}".</li>}
              {shown.map((entry, index) => {
                const Icon = entry.icon
                const selected = index === active
                return (
                  <li
                    key={entry.id}
                    id={`${listId}-${entry.id}`}
                    role="option"
                    aria-selected={selected}
                    onMouseMove={() => setActive(index)}
                    onClick={() => choose(entry)}
                    className={cn(
                      'relative flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 text-sm',
                      selected ? 'text-accent-foreground' : 'text-foreground',
                    )}
                  >
                    {selected && (
                      <motion.span
                        layoutId="quick-jump-active"
                        aria-hidden
                        className="absolute inset-0 rounded-md bg-accent"
                        transition={{ type: 'spring', stiffness: 520, damping: 40 }}
                      />
                    )}
                    <Icon size={16} aria-hidden className="relative shrink-0" />
                    <span className="relative flex-1 font-medium">{entry.label}</span>
                    <span className="relative text-xs text-muted-foreground">{entry.hint}</span>
                    {selected && <CornerDownLeft size={14} aria-hidden className="relative text-muted-foreground" />}
                  </li>
                )
              })}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
