import { useEffect, useId, useRef } from 'react'
import { X } from 'lucide-react'

import type { Role } from '../../api'
import { shortcutLabel } from './quickJumpKeys'

type Shortcut = { keys: string[]; does: string }

/** A group with roles is shown only to them: the review keys work on a page
 * students cannot open. */
const GROUPS: { title: string; where?: string; roles?: readonly Role[]; items: Shortcut[] }[] = [
  {
    title: 'Anywhere',
    items: [
      { keys: [shortcutLabel()], does: 'Go to a page or session' },
      { keys: ['?'], does: 'Show these shortcuts' },
      { keys: ['Esc'], does: 'Close a panel, a dialog or a search' },
    ],
  },
  {
    title: 'Reviewing questions',
    where: 'with a question selected',
    roles: ['lecturer', 'admin'],
    items: [
      { keys: ['J', 'K'], does: 'Next and previous question' },
      { keys: ['A'], does: 'Approve' },
      { keys: ['R'], does: 'Reject' },
      { keys: ['E'], does: 'Edit' },
      { keys: ['S'], does: 'Make an approved question ready to send' },
    ],
  },
]

/** Every keyboard shortcut the app has, so they can be found rather than
 * guessed. */
export default function ShortcutsSheet({ open, role, onClose }: { open: boolean; role: Role; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const node = dialog.current
    if (!node) return
    if (open && !node.open) node.showModal()
    else if (!open && node.open) node.close()
  }, [open])

  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose()
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-0 text-foreground shadow-[0_24px_60px_-24px_rgba(27,28,43,0.45)] backdrop:bg-[rgba(18,19,32,0.55)] backdrop:backdrop-blur-[2px] open:animate-in-up"
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 id={titleId} className="text-lg font-bold">
          Keyboard shortcuts
        </h2>
        <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X size={18} aria-hidden />
          <span className="sr-only">Close</span>
        </button>
      </div>
      <div className="max-h-[70vh] space-y-6 overflow-auto px-6 py-5">
        {GROUPS.filter((group) => !group.roles || group.roles.includes(role)).map((group) => (
          <section key={group.title}>
            <h3 className="text-sm font-semibold">
              {group.title}
              {group.where && <span className="font-normal text-muted-foreground">, {group.where}</span>}
            </h3>
            <dl className="mt-2 divide-y divide-border">
              {group.items.map((item) => (
                <div key={item.does} className="flex items-center justify-between gap-4 py-2">
                  <dt className="text-sm text-muted-foreground">{item.does}</dt>
                  <dd className="flex shrink-0 gap-1">
                    {item.keys.map((key) => (
                      <kbd
                        key={key}
                        className="min-w-[1.75rem] rounded border border-input bg-card px-1.5 py-0.5 text-center text-xs font-semibold shadow-[inset_0_-1px_0_var(--input)]"
                      >
                        {key}
                      </kbd>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </dialog>
  )
}
