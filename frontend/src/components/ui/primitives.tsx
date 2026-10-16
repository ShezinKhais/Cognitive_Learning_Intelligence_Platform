import type { ReactNode } from 'react'

import { cn } from './cn'



/** The top of a page: what it is, a line on what you do here, its actions. */
export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4 px-5 pb-5 pt-8 sm:px-8">
        <div className="max-w-2xl">
          <h1 className="text-[1.75rem] font-bold text-foreground">{title}</h1>
          {description && <p className="mt-1.5 text-muted-foreground">{description}</p>}
          {children}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

/** The page body under its header. */
export function PageBody({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={cn('mx-auto px-5 py-8 sm:px-8', wide ? 'max-w-7xl' : 'max-w-6xl')}>{children}</div>
  )
}

/** A bordered area of a page with an optional heading. */
export function Panel({
  title,
  description,
  actions,
  children,
  className,
  as: Tag = 'section',
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  as?: 'section' | 'article' | 'div'
}) {
  return (
    <Tag className={cn('rounded-lg border border-border bg-card', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            {title && <h2 className="text-lg font-bold">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      <div className="px-5 py-4">{children}</div>
    </Tag>
  )
}

export type Tone = 'neutral' | 'live' | 'good' | 'mixed' | 'poor' | 'info'

const TONE: Record<Tone, string> = {
  neutral: 'border-border bg-muted text-muted-foreground',
  live: 'border-highlight bg-highlight text-highlight-foreground',
  good: 'border-success/30 bg-success/10 text-success',
  mixed: 'border-warning/30 bg-warning/10 text-warning',
  poor: 'border-critical/30 bg-critical/10 text-critical',
  info: 'border-info/30 bg-info/10 text-info',
}

/** A short status in words, coloured by what it means. */
export function Tag({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold',
        TONE[tone],
      )}
    >
      {children}
    </span>
  )
}

/** Nothing here yet, and what to do about it. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="rounded-lg border border-dashed border-input bg-card px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
