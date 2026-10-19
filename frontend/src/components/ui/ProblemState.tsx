import { RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { Wordmark } from '../brand/ClipMark'
import { buttonStyles } from './button'
import { cn } from './cn'
import Illustration, { type IllustrationName } from './Illustration'

/**
 * Something could not be shown, with a picture of why, what to do, and a way
 * to try again. Inline it sits in the page like an empty state; full screen it
 * stands alone, for when even the account could not be checked.
 */
export function ProblemState({
  title,
  children,
  art = 'load-failed',
  action,
  retry,
  fullScreen = false,
}: {
  title: ReactNode
  children?: ReactNode
  art?: IllustrationName
  action?: ReactNode
  /** Shown as "Try again". Without it, and without an action, the page reloads. */
  retry?: () => void
  fullScreen?: boolean
}) {
  const buttons = (
    <div className={cn('mt-6 flex flex-wrap gap-2', !fullScreen && 'justify-center')}>
      {(retry || !action) && (
        <button type="button" onClick={retry ?? (() => window.location.reload())} className={buttonStyles()}>
          <RefreshCw size={16} aria-hidden />
          {retry ? 'Try again' : 'Reload'}
        </button>
      )}
      {action}
    </div>
  )

  if (fullScreen) {
    return (
      <main role="alert" className="min-h-screen bg-background px-4 py-10 sm:py-16">
        <div className="mx-auto w-full max-w-lg">
          <div className="mb-10">
            <Wordmark />
          </div>
          <Illustration name={art} className="h-40 w-56" />
          <h1 className="mt-8 text-[1.75rem] font-bold leading-tight">{title}</h1>
          {children && <p className="mt-2 text-muted-foreground">{children}</p>}
          {buttons}
        </div>
      </main>
    )
  }
  return (
    <div role="alert" className="rounded-lg border border-border bg-card px-6 py-10 text-center">
      <Illustration name={art} className="mx-auto mb-6 h-32 w-44" />
      <p className="text-lg font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{children}</p>}
      {buttons}
    </div>
  )
}
