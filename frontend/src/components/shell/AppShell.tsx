import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { LogOut, Menu, X } from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { clearAccessToken, type CurrentUser } from '../../api'
import { Wordmark as Brand } from '../brand/ClipMark'
import { cn } from '../ui/cn'
import IntroOverlay from './IntroOverlay'
import { introPlayed, takeIntro } from './intro'
import { currentItem, NAVIGATION, ROLE_NAME, type NavItem } from './navigation'

/**
 * The frame around every signed-in page outside Teams: a side menu for the
 * role, and the page beside it. Teams surfaces have their own frame, since
 * the meeting side panel is too narrow for one.
 */
export default function AppShell({ user, children }: { user: CurrentUser; children: ReactNode }) {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const items = NAVIGATION[user.role] ?? []
  const current = currentItem(user.role, pathname)
  const [intro, setIntro] = useState(takeIntro)
  const [entered, setEntered] = useState(!intro)
  const finishIntro = useCallback(() => {
    introPlayed()
    setIntro(false)
  }, [])

  // Close the phone menu when a link in it is followed.
  useEffect(() => setOpen(false), [pathname])

  const menu = (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-6">
      <MenuGroup items={items.filter((item) => !item.planned)} current={current} />
      {items.some((item) => item.planned) && (
        <div>
          <p className="px-3 pb-1 text-xs font-semibold text-muted-foreground">Planned</p>
          <MenuGroup items={items.filter((item) => item.planned)} current={current} />
        </div>
      )}
    </nav>
  )

  return (
    <LayoutGroup>
    <AnimatePresence onExitComplete={() => setEntered(true)}>
      {intro && <IntroOverlay firstName={user.full_name.split(' ')[0]} onDone={finishIntro} />}
    </AnimatePresence>
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[15rem_1fr]">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <header className="flex items-center justify-between border-b border-border bg-card px-4 py-3 lg:hidden">
        <Wordmark />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="phone-menu"
          className="rounded-md p-2 hover:bg-muted"
        >
          {open ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
          <span className="sr-only">{open ? 'Close menu' : 'Open menu'}</span>
        </button>
      </header>

      {open && (
        <div id="phone-menu" className="border-b border-border bg-card px-3 py-4 lg:hidden">
          {menu}
          <Account user={user} />
        </div>
      )}

      <aside className="sticky top-0 hidden h-screen flex-col gap-8 border-r border-border bg-card px-3 py-6 lg:flex">
        <div className="h-[2.6rem] px-3">
          {/* The intro's mark lands here. */}
          {!intro && (
            <motion.span layoutId="clip-brand" className="inline-flex" transition={{ type: 'spring', stiffness: 170, damping: 24 }}>
              <Wordmark />
            </motion.span>
          )}
        </div>
        {menu}
        <Account user={user} />
      </aside>

      <motion.main
        id="content"
        className="min-w-0"
        initial={false}
        animate={entered ? { opacity: 1, y: 0 } : { opacity: 0, y: 10 }}
        transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
      >
        {children}
      </motion.main>
    </div>
    </LayoutGroup>
  )
}

function Wordmark() {
  return (
    <Link to="/" aria-label="C.L.I.P home" className="inline-flex">
      <Brand />
    </Link>
  )
}

function MenuGroup({ items, current }: { items: NavItem[]; current?: NavItem }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = item === current
        return (
          <li key={item.to}>
            <Link
              to={item.to}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'relative flex items-center rounded-md px-3 py-2 text-[0.95rem] transition-colors',
                active
                  ? 'bg-accent font-semibold text-accent-foreground'
                  : 'text-foreground hover:bg-muted',
                item.planned && !active && 'text-muted-foreground',
              )}
            >
              {/* The highlighter marks where you are. */}
              {active && (
                <span aria-hidden className="absolute inset-y-1.5 left-0 w-1 rounded-full bg-highlight" />
              )}
              {item.label}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function Account({ user }: { user: CurrentUser }) {
  return (
    <div className="mt-auto border-t border-border px-3 pt-4">
      <p className="truncate text-sm font-semibold">{user.full_name}</p>
      <p className="truncate text-xs text-muted-foreground">
        {ROLE_NAME[user.role]}, {user.email}
      </p>
      <button
        type="button"
        onClick={() => {
          clearAccessToken()
          window.location.assign('/login')
        }}
        className="mt-3 inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <LogOut size={16} aria-hidden />
        Sign out
      </button>
    </div>
  )
}
