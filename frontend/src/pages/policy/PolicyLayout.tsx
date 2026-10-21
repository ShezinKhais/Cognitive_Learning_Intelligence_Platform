import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Wordmark } from '../../components/brand/ClipMark'
import { useDocumentTitle } from '../../components/ui/useDocumentTitle'
import { POLICY_UPDATED } from './policyFacts'

/** A readable policy page: open to anyone, signed in or not, and inside Teams. */
export function PolicyLayout({
  title,
  summary,
  other,
  children,
}: {
  title: string
  summary: string
  other: { to: string; label: string }
  children: ReactNode
}) {
  useDocumentTitle(title)
  return (
    <main className="min-h-screen bg-background px-4 py-10 sm:py-14">
      <article className="mx-auto w-full max-w-2xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Wordmark />
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft size={15} aria-hidden />
            Back to C.L.I.P
          </Link>
        </div>

        <h1 className="mt-10 text-[2rem] font-bold leading-tight">{title}</h1>
        <p className="mt-3 text-lg text-muted-foreground">{summary}</p>
        <p className="mt-4 text-sm text-muted-foreground">
          Last updated {POLICY_UPDATED}. See also the{' '}
          <Link to={other.to} className="font-semibold text-primary underline underline-offset-2">
            {other.label}
          </Link>
          .
        </p>

        <p className="mt-6 rounded-lg border border-info/30 bg-info/10 px-4 py-3 text-sm">
          C.L.I.P is a student capstone project (CSIT321 Team 4, University of Wollongong in Dubai)
          and is still in development. This page describes how the platform works today. It is
          awaiting review by the project team and the university, and is not a legal assessment.
        </p>

        <div className="mt-8 space-y-9">{children}</div>
      </article>
    </main>
  )
}

export function PolicySection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-bold">{title}</h2>
      <div className="mt-3 space-y-3 leading-relaxed text-foreground [&_li]:mt-1.5 [&_ul]:list-disc [&_ul]:pl-5">
        {children}
      </div>
    </section>
  )
}
