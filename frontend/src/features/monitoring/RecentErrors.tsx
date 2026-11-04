import { useEffect, useState } from 'react'

import { apiAuthenticatedGet } from '../../api'
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
  groups: ErrorGroup[]
}

/** Server errors and browser crashes since the server started, grouped. */
export default function RecentErrorsPanel({ refresh }: { refresh: number }) {
  const [recent, setRecent] = useState<RecentErrors | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiAuthenticatedGet<RecentErrors>('/admin/errors').then(
      (found) => {
        if (cancelled) return
        setRecent(found)
        setFailed(false)
      },
      () => !cancelled && setFailed(true),
    )
    return () => {
      cancelled = true
    }
  }, [refresh])

  return (
    <Panel
      title="Recent errors"
      description={recent ? sinceVerb('Counting since the server started', recent.since) : undefined}
      actions={recent && <Tag tone={recent.groups.length ? 'mixed' : 'good'}>{recent.total} logged</Tag>}
      className="md:col-span-2"
    >
      {failed ? (
        <p className="text-sm text-critical">The error log could not be read.</p>
      ) : !recent ? (
        <p className="text-muted-foreground">Checking…</p>
      ) : recent.groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing has gone wrong since the server started.</p>
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
    </Panel>
  )
}
