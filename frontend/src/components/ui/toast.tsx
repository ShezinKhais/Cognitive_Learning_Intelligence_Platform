import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, CheckCircle2, X } from 'lucide-react'

import { cn } from './cn'

/**
 * A short confirmation after an action: "Renamed", "Question sent". Read out
 * by screen readers through one polite live region, kept on screen while the
 * pointer or focus is on it, and never the only place an outcome is shown.
 */
type ToastTone = 'done' | 'problem'

interface Toast {
  id: number
  tone: ToastTone
  message: string
  action?: { label: string; run: () => void }
}

type Notify = (message: string, options?: { tone?: ToastTone; action?: Toast['action'] }) => void

const ToastContext = createContext<Notify>(() => undefined)

const SHOW_MS = 4500
let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => setToasts((current) => current.filter((toast) => toast.id !== id)), [])

  const notify = useCallback<Notify>((message, options) => {
    const toast: Toast = { id: nextId++, tone: options?.tone ?? 'done', message, action: options?.action }
    // Three at most; the oldest gives way.
    setToasts((current) => [...current.slice(-2), toast])
  }, [])

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 px-4 pb-4 sm:items-end sm:pr-6 sm:pb-6"
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <ToastCard key={toast.id} toast={toast} onDismiss={dismiss} />
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [held, setHeld] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (held) return
    timer.current = window.setTimeout(() => onDismiss(toast.id), SHOW_MS)
    return () => window.clearTimeout(timer.current)
  }, [held, onDismiss, toast.id])

  const Icon = toast.tone === 'problem' ? AlertTriangle : CheckCircle2
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, transition: { duration: 0.15 } }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      className="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-lg border border-border bg-popover py-2.5 pl-4 pr-2 text-sm text-popover-foreground shadow-[var(--shadow-card-hover)]"
    >
      <Icon size={17} aria-hidden className={cn('shrink-0', toast.tone === 'problem' ? 'text-critical' : 'text-success')} />
      <p className="min-w-0 flex-1">{toast.message}</p>
      {toast.action && (
        <button
          type="button"
          onClick={() => {
            toast.action?.run()
            onDismiss(toast.id)
          }}
          className="rounded-md px-2 py-1 font-semibold text-primary hover:bg-muted"
        >
          {toast.action.label}
        </button>
      )}
      <button type="button" onClick={() => onDismiss(toast.id)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
        <X size={15} aria-hidden />
        <span className="sr-only">Dismiss</span>
      </button>
    </motion.div>
  )
}

// oxlint-disable-next-line react/only-export-components
export function useToast(): Notify {
  return useContext(ToastContext)
}
