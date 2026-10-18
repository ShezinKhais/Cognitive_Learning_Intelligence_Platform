import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'

import { apiGet, apiUrl, type Health } from '../api'
import { buttonStyles } from '../components/ui/button'
import { PageBody, PageHeader, Panel, Tag } from '../components/ui/primitives'
import { ProblemState } from '../components/ui/ProblemState'

interface Dependency {
  name: string
  ok: boolean
  detail: string | null
  latency_ms: number | null
}

interface Readiness {
  ready: boolean
  checked_at: string
  dependencies: Dependency[]
}

const NAMES: Record<string, string> = { postgres: 'Database', ollama: 'AI models' }

/** /ready answers 503 when something is down, with the same body; read it
 * either way so the page can say what is wrong. */
async function readReadiness(): Promise<Readiness> {
  const response = await fetch(apiUrl('/ready'))
  return (await response.json()) as Readiness
}

export default function AdminStatusPage() {
  const [health, setHealth] = useState<Health | null>(null)
  const [ready, setReady] = useState<Readiness | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const check = useCallback(async () => {
    setChecking(true)
    setError(null)
    try {
      const [h, r] = await Promise.all([apiGet<Health>('/health'), readReadiness()])
      setHealth(h)
      setReady(r)
    } catch {
      setError('The backend did not answer. Check that it is running.')
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void check()
  }, [check])

  return (
    <>
      <PageHeader
        title="System status"
        description="Whether the database and AI models are reachable, and how this deployment is set up."
        actions={
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={check} disabled={checking}>
            <RefreshCw size={16} aria-hidden className={checking ? 'animate-spin' : undefined} />
            Check again
          </button>
        }
      />
      <PageBody>
        {error && !checking ? (
          <ProblemState art="server-down" title="The C.L.I.P server did not answer" retry={check}>
            {error}
          </ProblemState>
        ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <Panel
            title="Services"
            actions={ready && <Tag tone={ready.ready ? 'good' : 'poor'}>{ready.ready ? 'Ready' : 'Not ready'}</Tag>}
          >
            {!ready && <p className="text-muted-foreground">Checking…</p>}
            <ul className="divide-y divide-border">
              {ready?.dependencies.map((dependency) => (
                <li key={dependency.name} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div>
                    <p className="font-semibold">{NAMES[dependency.name] ?? dependency.name}</p>
                    {dependency.detail && <p className="text-sm text-muted-foreground">{dependency.detail}</p>}
                  </div>
                  <div className="text-right">
                    <Tag tone={dependency.ok ? 'good' : 'poor'}>{dependency.ok ? 'Reachable' : 'Unreachable'}</Tag>
                    {dependency.latency_ms !== null && (
                      <p className="mt-1 text-xs text-muted-foreground">{Math.round(dependency.latency_ms)} ms</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Deployment">
            {health ? (
              <dl className="divide-y divide-border">
                <Row label="Environment" value={health.env} />
                <Row label="Version" value={health.version} />
                <Row label="Microsoft Teams" value={health.teams_configured ? 'Connected' : 'Not connected'} />
              </dl>
            ) : (
              <p className="text-muted-foreground">Checking…</p>
            )}
          </Panel>
        </div>
        )}
      </PageBody>
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  )
}
