import { Link } from 'react-router'
import { ExternalLink } from 'lucide-react'

import { buttonStyles } from '../components/ui/button'
import { useDocumentTitle } from '../components/ui/useDocumentTitle'
import { MuteButton, UpdateList } from '../features/live/TeamsUpdatesSection'
import { useTeamsUpdates } from '../features/live/useTeamsUpdates'
import { reachNotice } from '../teams/lecturerUpdates'

/**
 * The small pop-up C.L.I.P opens for a lecturer in a Teams meeting when
 * something happens in their class: the latest update, the ones before it,
 * and the switch that mutes the pop-ups for the rest of the class. It shows
 * counts and course content only, since it may be on a shared screen.
 *
 * The session comes from ?sessionId=; the backend checks the caller runs it.
 */
export default function TeamsLecturerUpdatePage() {
  const sessionId = new URLSearchParams(window.location.search).get('sessionId') ?? ''
  useDocumentTitle('Class update')

  if (!sessionId) {
    return (
      <main className="p-4 text-sm">
        <p>This update has no class to show. Open C.L.I.P from the meeting&apos;s side panel.</p>
      </main>
    )
  }
  return <Updates sessionId={sessionId} />
}

function Updates({ sessionId }: { sessionId: string }) {
  const { updates, failed, saving, setMuted, reload } = useTeamsUpdates(sessionId)
  const [latest, ...earlier] = updates?.updates ?? []
  const notice = updates ? reachNotice(updates) : null

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-3 bg-background p-4 text-foreground">
      <header>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">C.L.I.P update</p>
        <h1 className="mt-1 text-lg font-bold leading-snug">
          {updates === null ? (failed ? 'Could not load the update' : 'Loading the update…') : (latest?.text ?? 'Nothing new in this class')}
        </h1>
      </header>

      {failed && updates === null && (
        <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={() => void reload()}>
          Try again
        </button>
      )}

      {updates && (
        <>
          {notice && <p className="text-sm text-warning">{notice}</p>}
          {earlier.length > 0 && (
            <section aria-labelledby="earlier-updates">
              <h2 id="earlier-updates" className="mb-1 text-sm font-semibold">
                Earlier
              </h2>
              <UpdateList updates={earlier} limit={4} />
            </section>
          )}
          <div className="mt-auto flex flex-wrap gap-2 pt-2">
            <MuteButton muted={updates.muted} saving={saving} onChange={setMuted} />
            <Link
              to={`/lecturer/teams/meeting?sessionId=${encodeURIComponent(sessionId)}`}
              className={buttonStyles({ intent: 'quiet' })}
            >
              <ExternalLink size={14} aria-hidden />
              Open the class panel
            </Link>
          </div>
          {updates.muted && (
            <p className="text-xs text-muted-foreground">Pop-ups are muted for the rest of this class.</p>
          )}
        </>
      )}
    </main>
  )
}
