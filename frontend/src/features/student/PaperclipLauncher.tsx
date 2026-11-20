import { Paperclip } from 'lucide-react'
import { motion } from 'motion/react'

import { paperclipLabel, paperclipScore } from './paperclip'

/**
 * The closed clip: a small button that opens C.L.I.P. A ring pulses around it
 * when a question is waiting, and the student's own checkpoint count sits
 * beside it. The ring and the tilt are travel, so reduced motion drops them.
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
      <motion.button
        type="button"
        onClick={onOpen}
        aria-expanded={false}
        aria-label={paperclipLabel(answered, delivered, questionOpen)}
        whileHover="hover"
        whileTap="tap"
        variants={{ hover: { scale: 1.05 }, tap: { scale: 0.95 } }}
        className="group relative inline-flex items-center gap-2 rounded-full border border-border bg-card/90 px-4 py-2 text-sm font-semibold shadow-[var(--shadow-card-hover)] backdrop-blur"
      >
        <motion.span
          aria-hidden
          className="inline-flex"
          variants={{ hover: { rotate: -18 } }}
          transition={{ type: 'spring', stiffness: 400, damping: 12 }}
        >
          <Paperclip size={18} className="text-primary" />
        </motion.span>
        {score && <span className="tabular-nums">{score}</span>}
        {questionOpen && (
          <span aria-hidden className="absolute -right-1 -top-1 size-3">
            <motion.span
              className="absolute inset-0 rounded-full bg-info"
              animate={{ scale: [1, 2.6], opacity: [0.55, 0] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }}
            />
            <span className="absolute inset-0 rounded-full bg-info ring-2 ring-background" />
          </span>
        )}
      </motion.button>
    </div>
  )
}
