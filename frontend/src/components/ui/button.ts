import { cva, type VariantProps } from 'class-variance-authority'

/** Buttons and links that act like them share one look per intent. */
export const buttonStyles = cva(
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold transition-[color,background-color,border-color,transform] duration-150 active:scale-[0.97] motion-reduce:active:scale-100 disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
  {
    variants: {
      intent: {
        primary: 'bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90',
        secondary: 'border border-input bg-card px-4 py-2 text-foreground hover:bg-muted',
        quiet: 'px-3 py-2 text-foreground hover:bg-muted',
        danger: 'border border-critical/40 bg-card px-4 py-2 text-critical hover:bg-critical/5',
      },
    },
    defaultVariants: { intent: 'primary' },
  },
)

export type ButtonIntent = VariantProps<typeof buttonStyles>['intent']
