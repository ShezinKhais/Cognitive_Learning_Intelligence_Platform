import { motion } from 'motion/react'

/** Heights of the four ticks, as a share of the mark. They read as the
 * session strip: a class answering, question by question. */
const TICKS = [0.42, 0.7, 0.55, 1] as const

/**
 * The C.L.I.P mark: four ticks, the last one in highlighter. `draw` grows
 * them in one after another, for the intro after signing in.
 */
export function ClipMark({ size = 28, draw = false }: { size?: number; draw?: boolean }) {
  const width = 4
  const gap = 3
  const total = TICKS.length * width + (TICKS.length - 1) * gap
  return (
    <svg width={size} height={size} viewBox={`0 0 ${total} ${total}`} aria-hidden className="shrink-0">
      {TICKS.map((height, index) => {
        const h = height * total
        const last = index === TICKS.length - 1
        return (
          <motion.rect
            key={index}
            x={index * (width + gap)}
            width={width}
            rx={1.5}
            fill={last ? 'var(--highlight)' : 'var(--primary)'}
            stroke={last ? 'var(--highlight-foreground)' : 'none'}
            strokeOpacity={last ? 0.25 : 0}
            strokeWidth={last ? 0.6 : 0}
            initial={draw ? { height: 0, y: total } : false}
            animate={{ height: h, y: total - h }}
            transition={{ delay: draw ? 0.12 * index : 0, type: 'spring', stiffness: 260, damping: 20 }}
          />
        )
      })}
    </svg>
  )
}

/** The mark beside the name. */
export function Wordmark({ size = 'regular' }: { size?: 'regular' | 'large' }) {
  const large = size === 'large'
  if (large) {
    return (
      <span className="inline-flex items-center gap-2.5">
        <ClipMark size={56} />
        <span className="text-5xl font-extrabold leading-none tracking-tight">C.L.I.P</span>
      </span>
    )
  }
  // The full name sits under the whole lockup on one line. Beside the mark it
  // had a third less room and broke over two cramped lines in the side menu.
  return (
    <span className="inline-flex flex-col">
      <span className="inline-flex items-center gap-2.5">
        <ClipMark size={26} />
        <span className="text-xl font-extrabold leading-none tracking-tight">C.L.I.P</span>
      </span>
      <span className="mt-1.5 whitespace-nowrap text-[0.66rem] leading-none text-muted-foreground">
        Cognitive Learning Intelligence Platform
      </span>
    </span>
  )
}
