import { useEffect, useId, useRef, type ReactNode } from 'react'

import { buttonStyles } from './button'

/**
 * Asks once before something that cannot be undone. Built on <dialog>, so
 * the page behind is inert, focus stays inside, and Escape cancels. Focus
 * starts on Cancel: the safe choice is the one a stray Enter makes.
 */
export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const bodyId = useId()

  useEffect(() => {
    const node = dialog.current
    if (!node) return
    if (open && !node.open) {
      node.showModal()
      cancel.current?.focus()
    } else if (!open && node.open) {
      node.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialog}
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onCancel={(event) => {
        // Escape. React keeps `open` in charge of the element.
        event.preventDefault()
        if (!busy) onCancel()
      }}
      onClick={(event) => {
        // A click on the backdrop lands on the dialog element itself.
        if (event.target === dialog.current && !busy) onCancel()
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-0 text-foreground shadow-[0_24px_60px_-24px_rgba(27,28,43,0.45)] backdrop:bg-[rgba(18,19,32,0.55)] backdrop:backdrop-blur-[2px] open:animate-in-up"
    >
      <div className="p-6">
        <h2 id={titleId} className="text-lg font-bold">
          {title}
        </h2>
        <div id={bodyId} className="mt-2 text-sm text-muted-foreground">
          {children}
        </div>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <button ref={cancel} type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" className={buttonStyles({ intent: 'danger' })} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
