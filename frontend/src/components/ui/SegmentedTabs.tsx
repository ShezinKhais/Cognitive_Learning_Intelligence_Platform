import { useId, useRef, type ReactNode } from 'react'
import { motion } from 'motion/react'

import { cn } from './cn'

export interface Segment<K extends string> {
  key: K
  label: ReactNode
}

/**
 * A row of tabs that switch what is shown below. One tab stop: Tab reaches
 * the chosen tab, the arrow keys (and Home, End) move between them, and the
 * fill slides to whichever is chosen.
 */
export default function SegmentedTabs<K extends string>({
  label,
  segments,
  value,
  onChange,
  stretch = false,
  className,
}: {
  label: string
  segments: Segment<K>[]
  value: K
  onChange: (key: K) => void
  stretch?: boolean
  className?: string
}) {
  const pill = useId()
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const last = segments.length - 1
    const next =
      event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : event.key === 'Home' ? 0
      : event.key === 'End' ? last
      : null
    if (next === null) return
    event.preventDefault()
    onChange(segments[next].key)
    buttons.current[next]?.focus()
  }

  return (
    <div role="tablist" aria-label={label} className={cn('flex gap-1 rounded-lg border border-border bg-card p-1', className)}>
      {segments.map((segment, index) => {
        const selected = segment.key === value
        return (
          <button
            key={segment.key}
            ref={(node) => {
              buttons.current[index] = node
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(segment.key)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              'relative inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors',
              stretch && 'flex-1',
              selected ? 'font-semibold text-primary-foreground' : 'text-foreground hover:bg-muted',
            )}
          >
            {selected && (
              <motion.span
                layoutId={pill}
                aria-hidden
                className="absolute inset-0 rounded-md bg-primary"
                transition={{ type: 'spring', stiffness: 460, damping: 38 }}
              />
            )}
            <span className="relative inline-flex items-center gap-2">{segment.label}</span>
          </button>
        )
      })}
    </div>
  )
}
