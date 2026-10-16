import { useState, type FormEvent } from 'react'

import { buttonStyles } from '../../components/ui/button'

/**
 * "Which breakout room are you in?" A student answers once, and again if
 * they move. The lecturer then sees that room's activity: when it talks and
 * answers, never what is said.
 */
export default function RoomConfirm({ onConfirm }: { onConfirm: (label: string) => boolean }) {
  const [label, setLabel] = useState('')
  const [room, setRoom] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [notSent, setNotSent] = useState(false)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = label.trim()
    if (!name) return
    if (onConfirm(name)) {
      setRoom(name)
      setEditing(false)
      setNotSent(false)
    } else {
      setNotSent(true)
    }
  }

  if (room && !editing) {
    return (
      <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span>
          You are in <strong>{room}</strong>.
        </span>
        <button type="button" className="font-semibold text-primary underline-offset-2 hover:underline" onClick={() => setEditing(true)}>
          Change room
        </button>
      </p>
    )
  }

  return (
    <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1 text-sm font-semibold">
        In a breakout room? Say which one
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          maxLength={100}
          placeholder="Room 3"
          className="mt-1.5 w-full rounded-md border border-input bg-input-background px-3 py-2 font-normal"
        />
      </label>
      <button type="submit" className={buttonStyles({ intent: 'secondary' })} disabled={!label.trim()}>
        Confirm room
      </button>
      {notSent && (
        <p role="alert" className="w-full text-sm text-critical">
          Not sent: you are not connected to the class right now. Try again in a moment.
        </p>
      )}
    </form>
  )
}
