import { Bell, BellOff } from 'lucide-react'

import { buttonStyles } from '../../components/ui/button'
import { reachNotice, updateAge, updateKindLabel, type TeamsUpdates } from '../../teams/lecturerUpdates'
import { useTeamsUpdates } from './useTeamsUpdates'

export function MuteButton({
  muted,
  saving,
  onChange,
}: {
  muted: boolean
  saving: boolean
  onChange: (muted: boolean) => void
}) {
  return (
    <button
      type="button"
      className={buttonStyles({ intent: 'secondary' })}
      aria-pressed={muted}
      disabled={saving}
      onClick={() => onChange(!muted)}
    >
      {muted ? <BellOff size={14} aria-hidden /> : <Bell size={14} aria-hidden />}
      {muted ? 'Turn pop-ups back on' : 'Mute pop-ups'}
    </button>
  )
}

export function UpdateList({ updates, limit }: { updates: TeamsUpdates['updates']; limit?: number }) {
  const shown = limit ? updates.slice(0, limit) : updates
  if (shown.length === 0) {
    return <p className="text-sm text-muted-foreground">No updates yet this class.</p>
  }
  return (
    <ul className="space-y-2">
      {shown.map((update, index) => (
        <li key={`${update.at}-${index}`} className="text-sm">
          <span className="text-xs font-semibold text-muted-foreground">
            {updateKindLabel(update.kind)} · {updateAge(update.at)}
          </span>
          <span className="block">{update.text}</span>
        </li>
      ))}
    </ul>
  )
}

/**
 * The side panel's view of the Teams pop-ups: who C.L.I.P cannot reach in
 * Teams, the latest updates, and the mute switch.
 */
export default function TeamsUpdatesSection({ sessionId }: { sessionId: string }) {
  const { updates, failed, saving, setMuted } = useTeamsUpdates(sessionId)
  // Nothing to show until the first read; a failed first read stays quiet,
  // since the panel's own controls do not depend on it.
  if (!updates) return null
  const notice = reachNotice(updates)
  return (
    <section aria-labelledby="panel-teams-updates" className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="panel-teams-updates" className="font-bold">
          Teams pop-ups
        </h2>
        <MuteButton muted={updates.muted} saving={saving} onChange={setMuted} />
      </div>
      {updates.muted && (
        <p className="mt-2 text-sm text-muted-foreground">
          Muted for the rest of the class. Updates are still listed here.
        </p>
      )}
      {notice && <p className="mt-2 text-sm text-warning">{notice}</p>}
      <div className="mt-2">
        <UpdateList updates={updates.updates} limit={3} />
      </div>
      {failed && <p className="mt-2 text-xs text-muted-foreground">Could not refresh the updates.</p>}
    </section>
  )
}
