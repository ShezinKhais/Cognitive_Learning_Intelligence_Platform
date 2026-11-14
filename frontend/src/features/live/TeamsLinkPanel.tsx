import { useId, useState, type FormEvent } from 'react'

import { ApiError, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { Panel } from '../../components/ui/primitives'
import type { SessionSummary } from '../sessions/sessionsApi'

function send(path: string, method: 'POST' | 'PUT', body: unknown): Promise<SessionSummary> {
  return apiAuthenticatedRequest<SessionSummary>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/**
 * Link this class to a Teams meeting from the website, by pasting the
 * meeting's join link. Once linked the two run together: the meeting
 * starting starts the class, the class starting opens C.L.I.P for everyone
 * in the call, joining and leaving the call count as joining and leaving the
 * class, and the class ends with the meeting or once everyone has left it.
 */
export default function TeamsLinkPanel({
  session,
  onChange,
}: {
  session: SessionSummary
  onChange: (session: SessionSummary) => void
}) {
  const id = useId()
  const [link, setLink] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const linked = Boolean(session.teams_meeting_id)

  async function run(work: () => Promise<SessionSummary>, failed: string) {
    setSaving(true)
    setError(null)
    try {
      onChange(await work())
      return true
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : failed)
      return false
    } finally {
      setSaving(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!link.trim()) return setError('Paste the meeting link from its Teams invitation.')
    const done = await run(
      () => send('/meetings/join-link', 'POST', { session_id: session.id, join_url: link.trim() }),
      'The meeting was not linked. Try again.',
    )
    if (done) setLink('')
  }

  function toggleLecturerLeaves(on: boolean) {
    void run(
      () =>
        send(`/meetings/sessions/${encodeURIComponent(session.id)}/end-when-lecturer-leaves`, 'PUT', {
          end_when_lecturer_leaves: on,
        }),
      'The change was not saved. Try again.',
    )
  }

  return (
    <Panel
      title="Teams meeting"
      description={
        linked
          ? 'Linked. The class starts and ends with the meeting, and follows who is in the call.'
          : 'Link a Teams meeting so the class starts and ends with it.'
      }
    >
      {linked ? (
        <>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>Starting the meeting starts this class. Starting the class opens C.L.I.P for everyone in the call.</li>
            <li>Students count as present as soon as they join the call, and leave the class when they leave it.</li>
            <li>Once everyone has left the call, the class ends after a short wait. You are warned first and can keep it running.</li>
          </ul>
          <label htmlFor={`${id}-lecturer`} className="mt-3 flex cursor-pointer items-start gap-2.5 border-t border-border pt-3 text-sm">
            <input
              id={`${id}-lecturer`}
              type="checkbox"
              className="mt-0.5 size-4 accent-[var(--primary)]"
              checked={Boolean(session.end_when_lecturer_leaves)}
              disabled={saving}
              onChange={(event) => toggleLecturerLeaves(event.target.checked)}
            />
            <span>
              <span className="font-medium">End the class when I leave the call</span>
              <span className="block text-xs text-muted-foreground">
                After the same short wait. Rejoining in time keeps it running.
              </span>
            </span>
          </label>
          {session.teams_join_url && (
            <a
              href={session.teams_join_url}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonStyles({ intent: 'secondary', className: 'mt-3' })}
            >
              Open the Teams call
            </a>
          )}
          {error && (
            <p role="alert" className="mt-1.5 text-xs text-critical">
              {error}
            </p>
          )}
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          <label htmlFor={`${id}-link`} className="text-xs text-muted-foreground">
            Meeting link
            <input
              id={`${id}-link`}
              type="url"
              value={link}
              disabled={saving}
              placeholder="https://teams.microsoft.com/l/meetup-join/..."
              onChange={(event) => setLink(event.target.value)}
              className="mt-1 w-full rounded-md border border-input bg-input-background px-2.5 py-1.5 text-sm"
            />
          </label>
          <p className="mt-1.5 text-xs text-muted-foreground">
            Add C.L.I.P to the meeting in Teams first (Apps, then C.L.I.P), then paste its link here.
          </p>
          {error && (
            <p role="alert" className="mt-1.5 text-xs text-critical">
              {error}
            </p>
          )}
          <button type="submit" disabled={saving} className={buttonStyles({ className: 'mt-2' })}>
            {saving ? 'Linking...' : 'Link meeting'}
          </button>
        </form>
      )}
    </Panel>
  )
}
