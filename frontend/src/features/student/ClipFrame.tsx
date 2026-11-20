import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'

// The clip sits at the top right of the panel, so everything unfolds from and
// folds back into that corner.
const CORNER = '100% 0%'
const UNFOLD = { type: 'spring', stiffness: 260, damping: 26 } as const

/**
 * Swaps the resting paperclip and the open panel. The panel unfolds out of the
 * clip: it grows from the corner while tipping forward from a folded edge, and
 * folds back the same way. Reduced motion keeps only the fade (MotionConfig in
 * main.tsx), so nothing travels for a student who asks for that.
 */
export default function ClipFrame({
  open,
  launcher,
  children,
}: {
  open: boolean
  launcher: ReactNode
  children: ReactNode
}) {
  return (
    <div style={{ perspective: 1200 }}>
      <AnimatePresence mode="wait" initial={false}>
        {open ? (
          <motion.div
            key="open"
            style={{ transformOrigin: CORNER }}
            initial={{ opacity: 0, scale: 0.5, rotateX: -38, y: -6 }}
            animate={{ opacity: 1, scale: 1, rotateX: 0, y: 0 }}
            exit={{ opacity: 0, scale: 0.55, rotateX: -28, transition: { duration: 0.18 } }}
            transition={UNFOLD}
          >
            {children}
          </motion.div>
        ) : (
          <motion.div
            key="closed"
            style={{ transformOrigin: CORNER }}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6, transition: { duration: 0.12 } }}
            transition={UNFOLD}
          >
            {launcher}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/**
 * One part of the open panel, arriving just after the one before it so the
 * panel fills in as it unfolds. Outside the clip it is just its children.
 */
export function Reveal({
  index,
  enabled,
  children,
}: {
  index: number
  enabled: boolean
  children: ReactNode
}) {
  if (!enabled) return <>{children}</>
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.12 + index * 0.06, type: 'spring', stiffness: 300, damping: 28 }}
    >
      {children}
    </motion.div>
  )
}
