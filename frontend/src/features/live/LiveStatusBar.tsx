import { useEffect, useState } from 'react'
import { Clock3, MessageSquareText, Pause, Play, Square, Users } from 'lucide-react'

import { buttonStyles } from '../../components/ui/button'
import { cn } from '../../components/ui/cn'
import { formatElapsed } from '../format/relativeTime'

function useElapsed(since: string | null | undefined, running: boolean): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])
  const start = since ? Date.parse(since) : Number.NaN
  return Number.isNaN(start) ? null : (now - start) / 1000
}

/**
 * The class at a glance, kept in reach while the lecturer scrolls the live
 * view: how long it has run, who is connected, the open question's time,
 * and the controls. Only while the class is running or paused.
 */
export default function LiveStatusBar({
  paused,
  startedAt,
  participants,
  questionOpen,
  secondsRemaining,
  canPause,
  canResume,
  canEnd,
  working,
  onPause,
  onResume,
  onEnd,
}: {
  paused: boolean
  startedAt: string | null | undefined
  participants: number
  questionOpen: boolean
  secondsRemaining: number
  canPause: boolean
  canResume: boolean
  canEnd: boolean
  working: 'pause' | 'resume' | 'end' | null
  onPause: () => void
  onResume: () => void
  onEnd: () => void
}) {
  const elapsed = useElapsed(startedAt, !paused)

  return (
    <div
      role="region"
      aria-label="Class status"
      className="sticky top-[var(--shell-header,0px)] z-20 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/85"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2 sm:gap-x-5 sm:px-8 sm:py-2.5">
        <span
          className={cn(
            'inline-flex items-center gap-2 text-sm font-semibold',
            paused ? 'text-warning' : 'text-foreground',
          )}
        >
          <span className="relative flex h-2 w-2" aria-hidden>
            {!paused && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-50 [animation-iteration-count:3]" />}
            <span className={cn('relative inline-flex h-2 w-2 rounded-full', paused ? 'bg-warning' : 'bg-primary')} />
          </span>
          {paused ? 'Paused' : 'Live'}
        </span>

        {elapsed !== null && (
          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Clock3 size={15} aria-hidden />
            <span className="sr-only">Running for</span>
            <span className="font-semibold tabular-nums text-foreground">{formatElapsed(elapsed)}</span>
          </span>
        )}

        <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          <Users size={15} aria-hidden />
          <span className="font-semibold tabular-nums text-foreground">{participants}</span>
          <span className="sr-only sm:not-sr-only">{participants === 1 ? 'student' : 'students'}</span>
        </span>

        <span
          className={cn('items-center gap-1.5 text-sm text-muted-foreground', questionOpen ? 'inline-flex' : 'hidden sm:inline-flex')}
          aria-live="polite"
        >
          <MessageSquareText size={15} aria-hidden />
          {questionOpen ? (
            <>
              Question open,
              <span className="font-semibold tabular-nums text-foreground">{secondsRemaining}s</span>
              left
            </>
          ) : (
            'No question open'
          )}
        </span>

        <span className="ml-auto flex gap-2">
          {paused ? (
            <button type="button" className={cn(buttonStyles({ intent: 'secondary' }), 'px-3 sm:px-4')} disabled={!canResume} onClick={onResume}>
              <Play size={15} aria-hidden />
              <span className="sr-only sm:not-sr-only">{working === 'resume' ? 'Resuming...' : 'Resume'}</span>
            </button>
          ) : (
            <button type="button" className={cn(buttonStyles({ intent: 'secondary' }), 'px-3 sm:px-4')} disabled={!canPause} onClick={onPause}>
              <Pause size={15} aria-hidden />
              <span className="sr-only sm:not-sr-only">{working === 'pause' ? 'Pausing...' : 'Pause'}</span>
            </button>
          )}
          <button type="button" className={buttonStyles({ intent: 'danger' })} disabled={!canEnd} onClick={onEnd}>
            <Square size={14} aria-hidden />
            {working === 'end' ? (
              'Ending...'
            ) : (
              <>
                <span className="sm:hidden">End</span>
                <span className="hidden sm:inline">End class</span>
              </>
            )}
          </button>
        </span>
      </div>
    </div>
  )
}
