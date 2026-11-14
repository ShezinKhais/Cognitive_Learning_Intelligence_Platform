import { useEffect, useState } from 'react'

import { apiAuthenticatedGet, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { MetaLine, Panel, Tag } from '../../components/ui/primitives'
import { sinceVerb } from '../format/relativeTime'

interface ErrorGroup {
  source: 'server' | 'client'
  level: string
  where: string
  message: string
  count: number
  first_at: string
  last_at: string
  request_id: string | null
}

interface RecentErrors {
  since: string
  total: number
  server_error_spike: boolean
  groups: ErrorGroup[]
}

/** Server errors and browser crashes since the server started, grouped. */
export default function RecentErrorsPanel({ refresh }: { refresh: number }) {
  const [recent, setRecent] = useState<RecentErrors | null>(null)
  const [failed, setFailed] = useState(false)
  // Bumped after a test error is sent, so the list reloads at once.
  const [tick, setTick] = useState(0)
  const [testing, setTesting] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')

  function sendTestError() {
    setTesting('sending')
    apiAuthenticatedRequest<void>('/admin/errors/synthetic', { method: 'POST' }).then(
      () => {
        setTesting('sent')
        setTick((value) => value + 1)
      },
      () => setTesting('failed'),
    )
  }

  useEffect(() => {
    let cancelled = false
    let pending = false
    const check = () => {
      if (pending) return
      pending = true
      void apiAuthenticatedGet<RecentErrors>('/admin/errors')
        .then(
          (found) => {
            if (cancelled) return
            setRecent(found)
            setFailed(false)
          },
          () => !cancelled && setFailed(true),
        )
        .finally(() => { pending = false })
    }
    check()
    const timer = window.setInterval(check, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [refresh, tick])

  return (
    <Panel
      title="Recent errors"
      description={recent ? sinceVerb('Counting since the server started', recent.since) : undefined}
      actions={recent && <Tag tone={recent.groups.length ? 'mixed' : 'good'}>{recent.total} logged</Tag>}
      className="md:col-span-2"
    >
      {!failed && recent?.server_error_spike && (
        <p role="alert" className="mb-3 text-sm text-critical">
          Server errors stayed elevated for two minutes. Check Services and the server error groups below.
        </p>
      )}
      {failed ? (
        <p className="text-sm text-critical">The error log could not be read.</p>
      ) : !recent ? (
        <p className="text-muted-foreground">Checking…</p>
      ) : recent.groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">No error groups in the last 24 hours.</p>
      ) : (
        <ul className="divide-y divide-border">
          {recent.groups.slice(0, 50).map((group) => (
            <li key={`${group.source}:${group.where}:${group.message}`} className="py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 font-semibold break-words">{group.message}</p>
                <div className="flex gap-2">
                  {group.count > 1 && <Tag>{group.count} times</Tag>}
                  <Tag tone={group.source === 'client' ? 'info' : group.level === 'WARNING' ? 'mixed' : 'poor'}>
                    {group.source === 'client' ? 'Browser' : group.level === 'WARNING' ? 'Security' : 'Server'}
                  </Tag>
                </div>
              </div>
              <MetaLine
                items={[
                  <span key="where" className="break-all whitespace-normal">
                    {group.where}
                  </span>,
                  sinceVerb('Last', group.last_at),
                  group.request_id ? `Request ${group.request_id}` : null,
                ]}
              />
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <button
          type="button"
          className={buttonStyles({ intent: 'quiet' })}
          disabled={testing === 'sending'}
          onClick={sendTestError}
        >
          {testing === 'sending' ? 'Sending…' : 'Send a test error'}
        </button>
        <span className="text-xs text-muted-foreground" role="status">
          {testing === 'sent'
            ? 'A synthetic server error was logged. It should appear above.'
            : testing === 'failed'
              ? 'The test error could not be sent.'
              : 'Checks that server errors reach this list. Recorded in the audit log.'}
        </span>
      </div>
    </Panel>
  )
}
