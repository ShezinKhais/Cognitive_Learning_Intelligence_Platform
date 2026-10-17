import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, LayoutGroup, motion } from 'motion/react'
import { LogOut, Menu, Search, X } from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { clearAccessToken, type CurrentUser } from '../../api'
import { Wordmark as Brand } from '../brand/ClipMark'
import { cn } from '../ui/cn'
import NotificationBell from '../../features/notifications/NotificationBell'
import IntroOverlay from './IntroOverlay'
import { introPlayed, takeIntro } from './intro'
import { currentItem, NAVIGATION, ROLE_NAME, type NavItem } from './navigation'
import QuickJump from './QuickJump'
import { shortcutLabel, useQuickJumpShortcut } from './quickJumpKeys'
import ThemeSwitch from './ThemeSwitch'

/**
 * The frame around every signed-in page outside Teams: a side menu for the
 * role, and the page beside it. Teams surfaces have their own frame, since
 * the meeting side panel is too narrow for one.
 */
export default function AppShell({ user, children }: { user: CurrentUser; children: ReactNode }) {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [jumping, setJumping] = useState(false)
  const items = NAVIGATION[user.role] ?? []
  const current = currentItem(user.role, pathname)
  const [intro, setIntro] = useState(takeIntro)
  const [entered, setEntered] = useState(!intro)
  const finishIntro = useCallback(() => {
    introPlayed()
    setIntro(false)
  }, [])
  const openJump = useCallback(() => setJumping(true), [])
  useQuickJumpShortcut(openJump)
  useRouteAnnouncement(current?.label)

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

  const jumpButton = (
    <button
      type="button"
      onClick={openJump}
      className="flex w-full items-center gap-2.5 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground transition-colors hover:border-input hover:text-foreground"
    >
      <Search size={15} aria-hidden />
      <span className="flex-1 text-left">Go to…</span>
      <kbd className="rounded border border-border px-1.5 text-xs" aria-label={`Shortcut ${shortcutLabel()}`}>
        {shortcutLabel()}
      </kbd>
    </button>
  )

  return (
    <LayoutGroup>
      <AnimatePresence onExitComplete={() => setEntered(true)}>
        {intro && <IntroOverlay firstName={user.full_name.split(' ')[0]} onDone={finishIntro} />}
      </AnimatePresence>
      <QuickJump user={user} open={jumping} onClose={() => setJumping(false)} />
      <div className="min-h-screen bg-background lg:grid lg:grid-cols-[15rem_1fr]">
        <a
          href="#content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2"
        >
          Skip to content
        </a>

        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-card/95 px-4 py-3 backdrop-blur lg:hidden">
          <Wordmark />
          <div className="flex items-center gap-1">
            <button type="button" onClick={openJump} className="rounded-md p-2 hover:bg-muted">
              <Search size={20} aria-hidden />
              <span className="sr-only">Go to</span>
            </button>
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
          </div>
        </header>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              id="phone-menu"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0, transition: { duration: 0.15 } }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="overflow-hidden border-b border-border bg-card lg:hidden"
            >
              <div className="flex flex-col gap-6 px-3 py-4">
                {menu}
                <Account user={user} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <aside className="sticky top-0 hidden h-screen flex-col gap-6 overflow-y-auto border-r border-border bg-card px-3 py-6 lg:flex">
          <div className="h-[2.6rem] px-3">
            {/* The intro's mark lands here. */}
            {!intro && (
              <motion.span layoutId="clip-brand" className="inline-flex" transition={{ type: 'spring', stiffness: 170, damping: 24 }}>
                <Wordmark />
              </motion.span>
            )}
          </div>
          {jumpButton}
          {menu}
          <Account user={user} />
        </aside>

        <motion.main
          id="content"
          tabIndex={-1}
          className="min-w-0 outline-none"
          initial={false}
          animate={entered ? { opacity: 1, y: 0 } : { opacity: 0, y: 10 }}
          transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
        >
          {/* A quick fade between pages, so a change of page reads as one. */}
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            {children}
          </motion.div>
        </motion.main>
      </div>
    </LayoutGroup>
  )
}

/**
 * After moving to another page: name it in the tab title, and put focus at
 * the top of the new page so a screen reader starts reading there and Tab
 * goes on from it. Not on the first load, where focus belongs to the browser.
 */
function useRouteAnnouncement(label: string | undefined) {
  const { pathname } = useLocation()
  const first = useRef(true)

  useEffect(() => {
    document.title = label ? `${label} · C.L.I.P` : 'C.L.I.P'
  }, [label])

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    const main = document.getElementById('content')
    const heading = main?.querySelector<HTMLElement>('h1')
    window.scrollTo({ top: 0 })
    if (heading) {
      heading.tabIndex = -1
      heading.focus({ preventScroll: true })
    } else {
      main?.focus({ preventScroll: true })
    }
  }, [pathname])
}

function Wordmark() {
  return (
    <Link to="/" aria-label="C.L.I.P home" className="inline-flex">
      <Brand />
    </Link>
  )
}

function MenuGroup({ items, current }: { items: NavItem[]; current?: NavItem }) {
  // One marker per menu (the phone and desktop menus are both mounted).
  const marker = useId()
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item) => {
        const active = item === current
        const Icon = item.icon
        return (
          <li key={item.to}>
            <Link
              to={item.to}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'group relative flex items-center gap-3 rounded-md px-3 py-2 text-[0.95rem] transition-colors',
                active ? 'font-semibold text-accent-foreground' : 'text-foreground hover:bg-muted',
                item.planned && !active && 'text-muted-foreground',
              )}
            >
              {/* Where you are: the fill and the highlighter slide to the new item. */}
              {active && (
                <motion.span
                  layoutId={`${marker}-fill`}
                  aria-hidden
                  className="absolute inset-0 rounded-md bg-accent"
                  transition={{ type: 'spring', stiffness: 420, damping: 36 }}
                >
                  <span className="absolute inset-y-1.5 left-0 w-1 rounded-full bg-highlight" />
                </motion.span>
              )}
              <Icon
                size={17}
                aria-hidden
                className={cn(
                  'relative shrink-0 transition-transform duration-150 group-hover:scale-110 motion-reduce:group-hover:scale-100',
                  !active && 'text-muted-foreground group-hover:text-foreground',
                )}
              />
              <span className="relative">{item.label}</span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function Account({ user }: { user: CurrentUser }) {
  return (
    <div className="mt-auto">
      <div className="mb-3 space-y-3">
        <NotificationBell user={user} />
        <div className="px-1">
          <ThemeSwitch />
        </div>
      </div>
      <div className="border-t border-border px-3 pt-4">
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
    </div>
  )
}
