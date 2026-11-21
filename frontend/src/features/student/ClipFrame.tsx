import { motion } from 'motion/react'
import type { ReactNode } from 'react'

// The clip sits at the top right of the panel, so the panel unfolds from there.
const CORNER = '100% 0%'

/**
 * The Teams side panel's entrance: it unfolds out of the paperclip's corner,
 * growing while tipping forward from a folded edge, then settles. Reduced
 * motion keeps only the fade (MotionConfig in main.tsx).
 */
export default function ClipFrame({ children }: { children: ReactNode }) {
  return (
    <div style={{ perspective: 1200 }}>
      <motion.div
        style={{ transformOrigin: CORNER }}
        initial={{ opacity: 0, scale: 0.5, rotateX: -38, y: -6 }}
        animate={{ opacity: 1, scale: 1, rotateX: 0, y: 0 }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
      >
        {children}
      </motion.div>
    </div>
  )
}

/**
 * One part of the panel, arriving just after the one before it so the panel
 * fills in as it unfolds. Outside the Teams side panel it is just its children.
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
