import { useEffect, useState } from 'react'
import { PhoneOff } from 'lucide-react'

import { ApiError, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import type { SessionEnding } from './useLiveSession'

/**
 * The linked Teams call has emptied, or the lecturer has left it: the class
 * ends on its own when the countdown runs out. The lecturer can end it now
 * or keep it running.
 */
export default function ClassEndingBanner({
  sessionId,
  ending,
  onKept,
  onEndNow,
}: {
  sessionId: string
  ending: SessionEnding
  onKept: () => void
  onEndNow: () => void
}) {
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const seconds = Math.max(0, Math.ceil((new Date(ending.ends_at).getTime() - now) / 1000))
  const who = ending.reason === 'everyone_left' ? 'Everyone has left the Teams call.' : 'You have left the Teams call.'

  async function keep() {
    setBusy(true)
    setError(null)
    try {
      await apiAuthenticatedRequest(`/meetings/sessions/${encodeURIComponent(sessionId)}/keep-running`, {
        method: 'POST',
      })
      onKept()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The class could not be kept running. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3"
    >
      <p className="flex min-w-0 items-start gap-2.5 text-sm">
        <PhoneOff aria-hidden="true" size={18} className="mt-0.5 shrink-0 text-warning" />
        <span>
          <span className="font-semibold">{who}</span>{' '}
          {seconds > 0 ? (
            <>
              The class ends in <span className="tabular-nums">{seconds}</span> s. End it now?
            </>
          ) : (
            'Ending the class...'
          )}
          {error && <span className="block text-xs text-critical">{error}</span>}
        </span>
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={keep} className={buttonStyles({ intent: 'secondary' })}>
          Keep running
        </button>
        <button type="button" disabled={busy} onClick={onEndNow} className={buttonStyles({ intent: 'danger' })}>
          End now
        </button>
      </div>
    </div>
  )
}
