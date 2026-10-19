import type { ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'

import { cn } from './cn'
import { useDocumentTitle } from './useDocumentTitle'
import Illustration, { type IllustrationName } from './Illustration'



/** Where a page one level down goes back to, top left above its title. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft size={15} aria-hidden />
      <span className="link-sweep">{children}</span>
    </Link>
  )
}

/** The top of a page: where it sits, what it is, a line on what you do here,
 * its actions. The tab is named after the title, or `tabTitle` when the
 * title is not plain text. */
export function PageHeader({
  title,
  description,
  actions,
  back,
  tabTitle,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  back?: { to: string; label: string }
  tabTitle?: string
  children?: ReactNode
}) {
  useDocumentTitle(tabTitle ?? (typeof title === 'string' ? title : undefined))
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-4 px-5 pb-5 pt-8 sm:px-8">
        <div className="max-w-2xl">
          {back && (
            <div className="mb-3">
              <BackLink to={back.to}>{back.label}</BackLink>
            </div>
          )}
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
export function PageBody({ children }: { children: ReactNode }) {
  // The same measure as PageHeader, so a page's content starts where its title does.
  return <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">{children}</div>
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
  art,
}: {
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
  art?: IllustrationName
}) {
  return (
    <div className="rounded-lg border border-dashed border-input bg-card px-6 py-10 text-center">
      {art && <Illustration name={art} className="mx-auto mb-6 h-32 w-44" />}
      <p className="font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

/**
 * Grey shapes where rows are about to appear, so the page keeps its layout
 * while it loads. The label is what a screen reader hears instead.
 */
export function SkeletonRows({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-label={label} className="space-y-2">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          aria-hidden
          className="rounded-lg border border-border bg-card px-5 py-4"
          style={{ opacity: 1 - index * 0.22 }}
        >
          <div className="skeleton h-3.5 w-24 rounded" />
          <div className="skeleton mt-3 h-4 w-2/3 max-w-md rounded" />
          <div className="skeleton mt-2 h-3 w-1/3 max-w-48 rounded" />
        </div>
      ))}
    </div>
  )
}

/** Facts about a row on one line, with a small dot between them, wrapping
 * whole facts rather than mid-fact on a narrow screen. Empty ones are left
 * out. */
export function MetaLine({ items, className }: { items: ReactNode[]; className?: string }) {
  const shown = items.filter((item) => item !== null && item !== undefined && item !== false && item !== '')
  return (
    <p className={cn('flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-muted-foreground', className)}>
      {shown.map((item, index) => (
        <span key={index} className="inline-flex items-center gap-2 whitespace-nowrap">
          {index > 0 && <span aria-hidden className="h-[3px] w-[3px] rounded-full bg-current opacity-60" />}
          {item}
          {index < shown.length - 1 && <span className="sr-only">,</span>}
        </span>
      ))}
    </p>
  )
}
