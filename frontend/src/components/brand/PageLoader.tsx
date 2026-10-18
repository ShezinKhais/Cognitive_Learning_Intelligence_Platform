import { motion } from 'motion/react'

const HEIGHTS = [0.42, 0.7, 0.55, 1] as const

/** While the app checks who you are: the mark's ticks rise in turn. Says
 * what it is doing for screen readers, and holds still with reduced motion. */
export default function PageLoader({ label = 'Checking your account' }: { label?: string }) {
  return (
    <main className="grid min-h-screen place-items-center bg-background" role="status" aria-live="polite">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-10 items-end gap-1.5" aria-hidden>
          {HEIGHTS.map((height, index) => (
            <motion.span
              key={index}
              className={`w-2 rounded-sm ${index === HEIGHTS.length - 1 ? 'bg-highlight' : 'bg-primary'}`}
              style={{ height: `${height * 100}%`, originY: 1 }}
              animate={{ scaleY: [1, 0.45, 1] }}
              transition={{ duration: 0.9, repeat: Infinity, delay: index * 0.12, ease: 'easeInOut' }}
            />
          ))}
        </div>
        <p className="text-sm text-muted-foreground">{label}…</p>
      </div>
    </main>
  )
}
