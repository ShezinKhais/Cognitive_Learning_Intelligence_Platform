import { Paperclip } from 'lucide-react'

import { paperclipLabel, paperclipScore } from './paperclip'

/**
 * The closed clip: a small button that opens C.L.I.P. A dot shows when a
 * question is waiting, and the student's own checkpoint count sits beside it.
 */
export default function PaperclipLauncher({
  answered,
  delivered,
  questionOpen,
  onOpen,
}: {
  answered: number
  delivered: number
  questionOpen: boolean
  onOpen: () => void
}) {
  const score = paperclipScore(answered, delivered)
  return (
    <div className="flex justify-end bg-background p-3">
      <button
        type="button"
        onClick={onOpen}
        aria-expanded={false}
        aria-label={paperclipLabel(answered, delivered, questionOpen)}
        className="relative inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm font-semibold shadow-[var(--shadow-card)] hover:bg-muted"
      >
        <Paperclip size={18} aria-hidden className="text-primary" />
        {score && <span className="tabular-nums">{score}</span>}
        {questionOpen && (
          <span aria-hidden className="absolute -right-1 -top-1 size-3 rounded-full bg-info ring-2 ring-background" />
        )}
      </button>
    </div>
  )
}
