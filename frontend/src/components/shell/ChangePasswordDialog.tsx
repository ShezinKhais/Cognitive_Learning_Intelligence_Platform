import { useEffect, useId, useRef, useState, type FormEvent } from 'react'

import { ApiError, apiAuthenticatedRequest } from '../../api'
import { buttonStyles } from '../ui/button'
import { useToast } from '../ui/toast'

const MIN_LENGTH = 12
const FIELD = 'mt-1 w-full rounded-md border border-input bg-input-background px-3 py-2'

function changePassword(current: string, next: string): Promise<void> {
  return apiAuthenticatedRequest<void>('/auth/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: current, new_password: next }),
  })
}

/** The signed-in user's own password, changed with the current one. */
export default function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const id = useId()
  const notify = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) element.showModal()
    if (!open && element.open) element.close()
  }, [open])

  function close() {
    setCurrent('')
    setNext('')
    setAgain('')
    setError(null)
    onClose()
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (next.length < MIN_LENGTH) return setError(`Use at least ${MIN_LENGTH} characters.`)
    if (next !== again) return setError('The new passwords do not match.')
    setSaving(true)
    setError(null)
    changePassword(current, next).then(
      () => {
        setSaving(false)
        notify('Password changed')
        close()
      },
      (caught: unknown) => {
        setSaving(false)
        setError(caught instanceof ApiError ? caught.message : 'The password was not changed. Try again.')
      },
    )
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby={`${id}-title`}
      onCancel={(event) => {
        event.preventDefault()
        close()
      }}
      className="w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-border bg-card p-6 text-foreground shadow-2xl backdrop:bg-black/40"
    >
      <form onSubmit={submit}>
        <h2 id={`${id}-title`} className="text-lg font-bold">
          Change your password
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          At least {MIN_LENGTH} characters. A few unrelated words are easier to remember than symbols.
        </p>
        <label htmlFor={`${id}-current`} className="mt-4 block text-sm font-semibold">
          Current password
        </label>
        <input
          id={`${id}-current`}
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          className={FIELD}
        />
        <label htmlFor={`${id}-next`} className="mt-3 block text-sm font-semibold">
          New password
        </label>
        <input
          id={`${id}-next`}
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_LENGTH}
          value={next}
          onChange={(event) => setNext(event.target.value)}
          className={FIELD}
        />
        <label htmlFor={`${id}-again`} className="mt-3 block text-sm font-semibold">
          New password again
        </label>
        <input
          id={`${id}-again`}
          type="password"
          autoComplete="new-password"
          required
          value={again}
          onChange={(event) => setAgain(event.target.value)}
          className={FIELD}
        />
        {error && (
          <p role="alert" className="mt-3 text-sm text-critical">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={close}>
            Cancel
          </button>
          <button type="submit" className={buttonStyles()} disabled={saving}>
            {saving ? 'Saving…' : 'Change password'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
