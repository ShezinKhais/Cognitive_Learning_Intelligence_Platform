import {
  useEffect,
  useState,
  type ReactNode,
} from 'react'

import { apiGet, type Health } from '../api'

export default function SystemStatusPage() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Health>('/health')
      .then(setHealth)
      .catch((caught: Error) => setError(caught.message))
  }, [])

  return (
    <main className="min-h-screen grid place-items-center p-8">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6">
        <h1 className="text-xl font-bold text-card-foreground">
          C.L.I.P
        </h1>

        <p className="mt-1 text-sm text-muted-foreground">
          Cognitive Learning Intelligence Platform
        </p>

        <dl className="mt-6 space-y-2 text-sm">
          <Row label="Backend">
            {error ? (
              <span className="text-critical">
                unreachable ({error})
              </span>
            ) : health ? (
              <span className="text-success">
                {health.status}
              </span>
            ) : (
              <span className="text-muted-foreground">
                checking
              </span>
            )}
          </Row>

          {health && (
            <>
              <Row label="Environment">
                {health.env}
              </Row>

              <Row label="Version">
                {health.version}
              </Row>

              <Row label="Teams">
                {health.teams_configured
                  ? 'configured'
                  : 'not configured'}
              </Row>
            </>
          )}
        </dl>
      </div>
    </main>
  )
}

function Row({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">
        {label}
      </dt>

      <dd className="font-medium">
        {children}
      </dd>
    </div>
  )
}
