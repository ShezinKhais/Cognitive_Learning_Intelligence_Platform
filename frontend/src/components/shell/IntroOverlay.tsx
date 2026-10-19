import { useEffect } from 'react'
import { motion } from 'motion/react'

import { ClipMark } from '../brand/ClipMark'

const HOLD_MS = 1150

/**
 * After signing in: the mark draws itself, a highlighter stroke sweeps behind
 * the name, and the whole thing then flies into the corner of the side menu
 * (the shared layoutId) while the page settles in beneath it. Any key or
 * click skips it.
 */
export default function IntroOverlay({ firstName, onDone }: { firstName: string; onDone: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, HOLD_MS)
    const skip = () => onDone()
    window.addEventListener('keydown', skip)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', skip)
    }
  }, [onDone])

  return (
    <motion.div
      className="fixed inset-0 z-50 grid place-items-center bg-background"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.35, delay: 0.15 } }}
      onClick={onDone}
      role="presentation"
    >
      <div className="flex flex-col items-center">
        <motion.span layoutId="clip-brand" className="inline-flex items-center gap-4" transition={{ type: 'spring', stiffness: 170, damping: 24 }}>
          <ClipMark size={64} draw />
          <span className="relative text-6xl font-extrabold tracking-tight">
            <motion.span
              aria-hidden
              className="absolute inset-x-[-0.15em] bottom-[0.12em] top-[0.45em] -z-10 origin-left rounded-sm bg-highlight"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ delay: 0.5, duration: 0.45, ease: [0.3, 0, 0.1, 1] }}
            />
            C.L.I.P
          </span>
        </motion.span>
        <motion.p
          className="mt-6 text-lg text-muted-foreground"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ delay: 0.7, duration: 0.3 }}
        >
          Welcome back, {firstName}
        </motion.p>
      </div>
    </motion.div>
  )
}
