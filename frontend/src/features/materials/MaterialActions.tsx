import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BookOpen, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'

import { ApiError } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import { useToast } from '../../components/ui/toast'
import { deleteMaterial, updateMaterial } from './materialApi'
import type { Material } from './types'
import { isFinished } from './upload'

type Mode = 'idle' | 'menu' | 'rename' | 'course' | 'delete'

/**
 * The "..." on a material's row. Rename and change course open a small form
 * in the row; delete asks first and says why when it is refused.
 */
export function MaterialMenu({ material, onMode }: { material: Material; onMode: (mode: Mode) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)

  const items = () => [...(list.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])]

  useEffect(() => {
    if (!open) return
    // Focus the first item once the menu is on screen.
    const frame = requestAnimationFrame(() => items()[0]?.focus())
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('mousedown', close)
    }
  }, [open])

  function closeAndReturn() {
    setOpen(false)
    trigger.current?.focus()
  }

  function onMenuKey(event: React.KeyboardEvent) {
    const all = items()
    const at = all.indexOf(document.activeElement as HTMLButtonElement)
    const move = (index: number) => {
      event.preventDefault()
      all[(index + all.length) % all.length]?.focus()
    }
    if (event.key === 'ArrowDown') move(at + 1)
    else if (event.key === 'ArrowUp') move(at - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(all.length - 1)
    else if (event.key === 'Escape') {
      event.preventDefault()
      closeAndReturn()
    } else if (event.key === 'Tab') setOpen(false)
  }

  function choose(mode: Mode) {
    setOpen(false)
    onMode(mode)
  }

  const item =
    'flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50'
  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        className={buttonStyles({ intent: 'quiet' })}
        title="More actions"
      >
        <MoreHorizontal size={16} aria-hidden />
        <span className="sr-only">More actions for {material.filename}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={list}
            role="menu"
            aria-label={`Actions for ${material.filename}`}
            onKeyDown={onMenuKey}
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, transition: { duration: 0.1 } }}
            transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}
            style={{ transformOrigin: 'top right' }}
            className="absolute right-0 top-full z-30 mt-1 w-52 overflow-hidden rounded-md border border-border bg-popover py-1 shadow-[var(--shadow-card-hover)]"
          >
            <button type="button" role="menuitem" tabIndex={-1} className={item} onClick={() => choose('rename')}>
              <Pencil size={15} aria-hidden /> Rename
            </button>
            <button type="button" role="menuitem" tabIndex={-1} className={item} onClick={() => choose('course')}>
              <BookOpen size={15} aria-hidden /> Change course
            </button>
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={`${item} text-critical`}
              onClick={() => choose('delete')}
              disabled={!isFinished(material)}
              aria-describedby={isFinished(material) ? undefined : `${material.id}-delete-why`}
            >
              <Trash2 size={15} aria-hidden /> Delete
            </button>
            {!isFinished(material) && (
              <p id={`${material.id}-delete-why`} className="px-3 pb-1.5 pt-0.5 text-xs text-muted-foreground">
                Delete once it has finished processing.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** The form a menu choice opens under the row. */
export function MaterialActionForm({
  mode,
  material,
  onClose,
  onChanged,
  onDeleted,
}: {
  mode: Exclude<Mode, 'idle' | 'menu'>
  material: Material
  onClose: () => void
  onChanged: (material: Material) => void
  onDeleted: (id: string) => void
}) {
  const [value, setValue] = useState(mode === 'rename' ? material.filename : (material.course_code ?? ''))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const notify = useToast()

  useEffect(() => {
    input.current?.focus()
    if (mode === 'rename') {
      // Select the name without its extension, as a file manager does.
      const dot = material.filename.lastIndexOf('.')
      input.current?.setSelectionRange(0, dot > 0 ? dot : material.filename.length)
    }
  }, [mode, material.filename])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setProblem(null)
    try {
      await action()
    } catch (caught: unknown) {
      setProblem(caught instanceof ApiError ? caught.message : 'That did not work. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (mode === 'rename') {
      const name = value.trim()
      if (!name || name === material.filename) return onClose()
      void run(async () => {
        onChanged(await updateMaterial(material.id, { filename: name }))
        notify(`Renamed to ${name}`)
        onClose()
      })
    } else if (mode === 'course') {
      void run(async () => {
        const updated = await updateMaterial(material.id, { course_code: value.trim() || null })
        onChanged(updated)
        notify(updated.course_code ? `Filed under ${updated.course_code}` : 'Now offered to any course')
        onClose()
      })
    }
  }

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="overflow-hidden"
      onKeyDown={(event) => event.key === 'Escape' && onClose()}
    >
      <div className="border-t border-border bg-background/60 px-5 py-4">
        {mode === 'delete' ? (
          <div>
            <p className="font-semibold">Delete {material.filename}?</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Its questions and what was read from it go too. This cannot be undone.
            </p>
            {problem && <p role="alert" className="mt-2 text-sm text-critical">{problem}</p>}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className={buttonStyles({ intent: 'danger' })}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await deleteMaterial(material.id)
                    notify(`Deleted ${material.filename}`)
                    onDeleted(material.id)
                  })
                }
              >
                {busy ? 'Deleting…' : 'Delete'}
              </button>
              <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={onClose}>
                Keep it
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
            <label className="min-w-0 flex-1 text-sm font-semibold">
              {mode === 'rename' ? 'Name' : 'Course code'}
              <input
                ref={input}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                maxLength={mode === 'rename' ? 255 : 20}
                placeholder={mode === 'course' ? 'CSIT321, or leave empty for any course' : undefined}
                className="mt-1.5 w-full rounded-md border border-input bg-input-background px-3 py-2 font-normal"
              />
            </label>
            <button type="submit" className={buttonStyles()} disabled={busy}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={onClose}>
              Cancel
            </button>
            {mode === 'course' && (
              <p className="w-full text-sm text-muted-foreground">
                Filed under a course, its questions are offered only to that course's sessions.
              </p>
            )}
            {problem && <p role="alert" className="w-full text-sm text-critical">{problem}</p>}
          </form>
        )}
      </div>
    </motion.div>
  )
}

export type MaterialActionMode = Mode
