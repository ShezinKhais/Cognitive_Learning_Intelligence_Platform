import { useId, useState } from 'react'
import { roomSelection } from './breakoutRoom'
import type { LiveErrorEvent } from './liveSessionTypes'

export function BreakoutRoomSelection({ enabled, onSelect, serverError }: {
  enabled: boolean
  onSelect: (label: string) => boolean
  serverError: LiveErrorEvent | null
}) {
  const id = useId()
  const [label, setLabel] = useState('')
  const [notice, setNotice] = useState('')
  const rejected = serverError &&
    ['ROOM_LIMIT', 'ROOM_LABEL_INVALID', 'NOT_IN_SESSION', 'RATE_LIMITED'].includes(serverError.code)
  return <section aria-labelledby={`${id}-title`} className="mt-5 rounded-xl border border-border bg-card p-5">
    <h2 id={`${id}-title`} className="text-lg font-semibold">Your breakout room</h2>
    <p id={`${id}-help`} className="mt-2 text-sm text-muted-foreground">
      Enter the room your lecturer assigned. This reports your selection to C.L.I.P;
      it does not create or move you into a Teams room. Camera and microphone are not required.
    </p>
    <form className="mt-3 flex flex-wrap items-end gap-3" onSubmit={event => {
      event.preventDefault()
      const selection = roomSelection(label)
      if (!selection) {
        setNotice('Enter a room name of 1–100 characters without control characters.')
        return
      }
      setNotice(enabled && onSelect(selection.room_label)
        ? `Room selection sent: ${selection.room_label}. Ask your lecturer if you need confirmation.`
        : 'Not sent. Wait for the active live connection and try again.')
    }}>
      <div>
        <label htmlFor={`${id}-room`} className="block text-sm font-medium">Assigned room name</label>
        <input id={`${id}-room`} aria-describedby={`${id}-help`} value={label}
          onChange={event => { setLabel(event.target.value); setNotice('') }}
          disabled={!enabled} maxLength={100} required
          className="mt-1 rounded-lg border border-border bg-background px-3 py-2 text-foreground" />
      </div>
      <button disabled={!enabled} type="submit"
        className="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50">
        Send room selection
      </button>
    </form>
    <p role="status" className="mt-2 text-sm text-muted-foreground">
      {!enabled ? 'Available while connected to an active, unpaused session. Send your selection again after reconnecting.'
        : rejected ? `Room selection may not have been accepted. ${serverError.detail ?? 'Try again or ask your lecturer.'}`
        : notice}
    </p>
  </section>
}
