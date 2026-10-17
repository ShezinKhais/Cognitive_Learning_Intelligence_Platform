import { useId } from 'react'
import { motion } from 'motion/react'
import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'

import { cn } from '../ui/cn'
import { THEME_CHOICES, useThemeChoice, type ThemeChoice } from './theme'

const LABEL: Record<ThemeChoice, { name: string; icon: LucideIcon }> = {
  system: { name: 'Match device', icon: Monitor },
  light: { name: 'Light', icon: Sun },
  dark: { name: 'Dark', icon: Moon },
}

/** Three-way light, dark or device theme, in the side menu. */
export default function ThemeSwitch() {
  const [choice, setChoice] = useThemeChoice()
  const pill = useId()

  return (
    <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-0.5 rounded-md border border-border bg-background p-0.5">
      {THEME_CHOICES.map((option) => {
        const { name, icon: Icon } = LABEL[option]
        const selected = option === choice
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={selected}
            title={name}
            onClick={() => setChoice(option)}
            className={cn(
              'relative grid h-8 place-items-center rounded-[calc(var(--radius)-2px)] transition-colors',
              selected ? 'text-accent-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {selected && (
              <motion.span
                layoutId={pill}
                aria-hidden
                className="absolute inset-0 rounded-[calc(var(--radius)-2px)] bg-accent"
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              />
            )}
            <Icon size={15} aria-hidden className="relative" />
            <span className="sr-only">{name}</span>
          </button>
        )
      })}
    </div>
  )
}
