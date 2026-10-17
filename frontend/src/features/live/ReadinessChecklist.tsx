import { Check, Circle, LoaderCircle, RefreshCw } from 'lucide-react'
import { Link } from 'react-router'

import { readinessItems } from './readinessItems'
import type { SessionReadiness } from './sessionActions'

export default function ReadinessChecklist({
  readiness,
  loading,
  error,
  busy,
  onRefresh,
}: {
  readiness: SessionReadiness | null
  loading: boolean
  error: string | null
  busy: boolean
  onRefresh: () => void
}) {
  return (
    <div className="mt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-bold">Before you start</h3>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading || busy}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw size={14} aria-hidden className={loading ? 'animate-spin' : undefined} />
          Check again
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-critical">
          {error}
        </p>
      )}
      {!readiness && loading && <p role="status" className="mt-3 text-sm text-muted-foreground">Checking…</p>}
      {readiness && (
        <ul className="mt-3 divide-y divide-border rounded-md border border-border">
          {readinessItems(readiness).map((item) => (
            <li key={item.title} className="flex items-start gap-3 px-4 py-3">
              <span
                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                  item.done ? 'bg-success text-success-foreground' : 'border border-input text-muted-foreground'
                }`}
              >
                {item.done ? (
                  <Check size={13} aria-hidden />
                ) : item.working ? (
                  <LoaderCircle size={13} aria-hidden className="animate-spin" />
                ) : (
                  <Circle size={6} aria-hidden fill="currentColor" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">
                  {item.title}
                  <span className="sr-only">{item.done ? ', done' : ', not done yet'}</span>
                </span>
                <span className="block text-sm text-muted-foreground">{item.detail}</span>
              </span>
              {item.link && (
                <Link to={item.link.to} className="shrink-0 text-sm font-semibold text-primary link-sweep">
                  {item.link.label}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
      {readiness && readiness.warnings.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-warning">
          {readiness.warnings.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
