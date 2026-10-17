import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, FileText, Presentation, Upload } from 'lucide-react'
import { Link } from 'react-router'

import { ApiError, clearAccessToken } from '../api'
import { cn } from '../components/ui/cn'
import { buttonStyles } from '../components/ui/button'
import { EmptyState, PageBody, PageHeader, Tag, SkeletonRows } from '../components/ui/primitives'
import { MaterialActionForm, MaterialMenu, type MaterialActionMode } from '../features/materials/MaterialActions'
import MaterialDetails from '../features/materials/MaterialDetails'
import { getMaterial, listMaterials, uploadMaterial } from '../features/materials/materialApi'
import type { Material, MaterialProgress } from '../features/materials/types'
import {
  ACCEPT_ATTRIBUTE,
  fileExtension,
  formatBytes,
  isFinished,
  progressFromStatus,
  STAGE_WORDS,
  upsertMaterial,
  validateUpload,
} from '../features/materials/upload'
import { useMaterialProgress } from '../features/materials/useMaterialProgress'
import { formatWhen } from '../features/sessions/format'

const PIPELINE_ENABLED = import.meta.env.VITE_MATERIAL_PIPELINE_ENABLED === 'true'
// When live updates are not reaching this tab, unfinished materials are
// checked this often instead.
const POLL_MS = 5000

interface Uploading {
  key: string
  name: string
  size: number
}

function signInAgain(): void {
  clearAccessToken()
  window.location.assign('/login')
}

export default function LecturerMaterialsPage() {
  const input = useRef<HTMLInputElement>(null)
  const [materials, setMaterials] = useState<Material[] | null>(null)
  const [progress, setProgress] = useState<Record<string, MaterialProgress>>({})
  const [uploading, setUploading] = useState<Uploading[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)

  const refresh = useCallback(async (id: string) => {
    try {
      const found = await getMaterial(id)
      setMaterials((current) => upsertMaterial(current ?? [], found))
      if (isFinished(found)) setProgress((current) => ({ ...current, [id]: progressFromStatus(found) }))
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) signInAgain()
    }
  }, [])

  useEffect(() => {
    listMaterials()
      .then((found) => setMaterials([...found].sort((a, b) => Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at))))
      .catch((caught: unknown) => {
        if (caught instanceof ApiError && caught.status === 401) return signInAgain()
        setMaterials([])
        setProblem('Your materials could not be loaded. Check your connection and reload the page.')
      })
  }, [])

  const receive = useCallback(
    (next: MaterialProgress) => {
      setProgress((current) => ({ ...current, [next.material_id]: next }))
      if (next.stage === 'done' || next.stage === 'failed') void refresh(next.material_id)
    },
    [refresh],
  )

  const unfinished = (materials ?? []).filter((m) => !isFinished(m)).map((m) => m.id)
  const recover = useCallback(() => unfinished.forEach((id) => void refresh(id)), [unfinished, refresh])
  const connection = useMaterialProgress(receive, { enabled: PIPELINE_ENABLED, onReconnect: recover })

  const unfinishedKey = unfinished.join(',')
  useEffect(() => {
    if (connection === 'connected' || !unfinishedKey) return
    const timer = window.setInterval(() => unfinishedKey.split(',').forEach((id) => void refresh(id)), POLL_MS)
    return () => window.clearInterval(timer)
  }, [connection, unfinishedKey, refresh])

  async function upload(file: File) {
    const refused = validateUpload(file)
    if (refused) return setProblem(`${file.name}: ${refused}`)
    setProblem(null)
    const key = `${file.name}-${Date.now()}`
    setUploading((current) => [{ key, name: file.name, size: file.size }, ...current])
    try {
      const created = await uploadMaterial(file)
      setMaterials((current) => upsertMaterial(current ?? [], created))
      setProgress((current) => (current[created.id] ? current : { ...current, [created.id]: progressFromStatus(created) }))
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) return signInAgain()
      setProblem(`${file.name}: ${caught instanceof ApiError ? caught.message : 'the upload did not finish. Try again.'}`)
    } finally {
      setUploading((current) => current.filter((item) => item.key !== key))
    }
  }

  function uploadAll(files: FileList | null) {
    for (const file of Array.from(files ?? [])) void upload(file)
  }

  // A file dropped anywhere on the page is uploaded.
  const dropHandlers = PIPELINE_ENABLED
    ? {
        onDragEnter: (event: DragEvent) => {
          if (!event.dataTransfer.types.includes('Files')) return
          dragDepth.current += 1
          setDragging(true)
        },
        onDragLeave: () => {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (dragDepth.current === 0) setDragging(false)
        },
        onDragOver: (event: DragEvent) => event.preventDefault(),
        onDrop: (event: DragEvent) => {
          event.preventDefault()
          dragDepth.current = 0
          setDragging(false)
          uploadAll(event.dataTransfer.files)
        },
      }
    : {}

  const empty = materials !== null && materials.length === 0 && uploading.length === 0

  return (
    <div className="relative min-h-screen" {...dropHandlers}>
      <PageHeader
        title="Materials"
        description="Upload a lecture and C.L.I.P drafts questions from it. You approve them before any reaches a class."
        actions={
          PIPELINE_ENABLED && (
            <>
              <input
                ref={input}
                type="file"
                accept={ACCEPT_ATTRIBUTE}
                multiple
                className="sr-only"
                onChange={(event) => {
                  uploadAll(event.target.files)
                  event.target.value = ''
                }}
              />
              <button type="button" className={buttonStyles()} onClick={() => input.current?.click()}>
                <Upload size={16} aria-hidden />
                Upload
              </button>
            </>
          )
        }
      />
      <PageBody>
        {!PIPELINE_ENABLED && (
          <p role="status" className="mb-6 rounded-md border border-info/30 bg-info/5 px-4 py-3 text-sm">
            Uploading is switched off in this build.
          </p>
        )}
        {problem && (
          <p role="alert" className="mb-6 rounded-md border border-critical/30 bg-critical/5 px-4 py-3 text-sm text-critical">
            {problem}
          </p>
        )}

        {materials === null && <SkeletonRows label="Loading your materials" />}

        {empty && (
          <EmptyState
            art="add-files"
            title="No materials yet"
            action={
              PIPELINE_ENABLED && (
                <button type="button" className={buttonStyles()} onClick={() => input.current?.click()}>
                  Choose a file
                </button>
              )
            }
          >
            Drop a PDF, PowerPoint, Word or text file anywhere on this page, up to 50 MB. Each one becomes questions
            you can review.
          </EmptyState>
        )}

        {(uploading.length > 0 || (materials?.length ?? 0) > 0) && (
          <ul className="overflow-hidden rounded-lg border border-border bg-card" aria-label="Your materials">
            {uploading.map((item) => (
              <li key={item.key} className="border-b border-border last:border-b-0">
                <Row
                  name={item.name}
                  meta={`${formatBytes(item.size)}, uploading`}
                  bar={{ percent: 2, label: 'Uploading' }}
                />
              </li>
            ))}
            {materials?.map((material) => (
              <li key={material.id} className="border-b border-border last:border-b-0">
                <MaterialRow
                  material={material}
                  progress={progress[material.id] ?? progressFromStatus(material)}
                  open={open === material.id}
                  onToggle={() => setOpen((current) => (current === material.id ? null : material.id))}
                  onChanged={(changed) => setMaterials((current) => upsertMaterial(current ?? [], changed))}
                  onDeleted={(id) => setMaterials((current) => (current ?? []).filter((item) => item.id !== id))}
                />
              </li>
            ))}
          </ul>
        )}

        {PIPELINE_ENABLED && !empty && materials !== null && (
          <p className="mt-3 text-sm text-muted-foreground">You can also drop files anywhere on this page.</p>
        )}
      </PageBody>

      <AnimatePresence>
        {dragging && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="pointer-events-none absolute inset-3 z-20 grid place-items-center rounded-xl border-2 border-dashed border-primary bg-accent/80"
          >
            <p className="text-lg font-bold text-accent-foreground">Drop to upload</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function MaterialRow({
  material,
  progress,
  open,
  onToggle,
  onChanged,
  onDeleted,
}: {
  material: Material
  progress: MaterialProgress
  open: boolean
  onToggle: () => void
  onChanged: (material: Material) => void
  onDeleted: (id: string) => void
}) {
  const [mode, setMode] = useState<MaterialActionMode>('idle')
  const working = !isFinished(material) && progress.stage !== 'done' && progress.stage !== 'failed'
  const failed = material.status === 'failed' || progress.stage === 'failed'
  const ready = material.status === 'completed'
  const pages = material.page_count
  const meta = [
    formatWhen(material.uploaded_at, ''),
    material.course_code ?? 'Any course',
    pages != null && `${pages} ${fileExtension(material.filename) === 'pptx' ? (pages === 1 ? 'slide' : 'slides') : pages === 1 ? 'page' : 'pages'}`,
    formatBytes(material.size_bytes),
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <>
      {/* The whole row opens it; its links and buttons keep their own job. */}
      <div
        className="cursor-pointer transition-colors hover:bg-muted/50"
        onClick={(event) => {
          if (!(event.target as HTMLElement).closest('a, button')) onToggle()
        }}
      >
      <Row
        name={material.filename}
        meta={meta}
        icon={fileExtension(material.filename) === 'pptx' ? Presentation : FileText}
        status={
          ready ? <Tag tone="good">Ready</Tag> : failed ? <Tag tone="poor">Failed</Tag> : <Tag tone="info">Processing</Tag>
        }
        bar={working ? { percent: progress.percent, label: STAGE_WORDS[progress.stage] } : undefined}
        note={failed ? (material.error ?? progress.message ?? 'It could not be processed. Upload it again.') : undefined}
        actions={
          <>
            {ready && (
              <Link to={`/materials/${material.id}/review`} className={buttonStyles({ intent: 'secondary' })}>
                Review questions
              </Link>
            )}
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              className={buttonStyles({ intent: 'quiet' })}
              title={open ? 'Hide details' : 'Show what was read'}
            >
              <ChevronDown size={16} aria-hidden className={cn('transition-transform duration-200', open && 'rotate-180')} />
              <span className="sr-only">{open ? 'Hide details' : 'Show what was read'}</span>
            </button>
            <MaterialMenu material={material} onMode={setMode} />
          </>
        }
      />
      </div>
      <AnimatePresence initial={false}>
        {mode !== 'idle' && mode !== 'menu' && (
          <MaterialActionForm
            key={mode}
            mode={mode}
            material={material}
            onClose={() => setMode('idle')}
            onChanged={onChanged}
            onDeleted={onDeleted}
          />
        )}
      </AnimatePresence>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
            className="overflow-hidden"
          >
            <MaterialDetails material={material} />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

function Row({
  name,
  meta,
  icon: Icon = FileText,
  status,
  bar,
  note,
  actions,
}: {
  name: string
  meta: string
  icon?: typeof FileText
  status?: ReactNode
  bar?: { percent: number; label: string }
  note?: string
  actions?: ReactNode
}) {
  return (
    <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 px-5 py-4 sm:grid-cols-[auto_1fr_auto]">
      <Icon size={22} aria-hidden className="text-muted-foreground" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-semibold">{name}</span>
          {status}
        </div>
        <p className="text-sm text-muted-foreground">{meta}</p>
        {bar && (
          <div className="mt-2 max-w-md" aria-live="polite">
            <div
              className="h-1.5 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={`${name}: ${bar.label}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(bar.percent)}
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
                style={{ width: `${Math.max(3, Math.min(100, bar.percent))}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{bar.label}</p>
          </div>
        )}
        {note && <p className="mt-1 text-sm text-critical">{note}</p>}
      </div>
      {actions && <div className="col-span-2 flex items-center gap-1 sm:col-span-1">{actions}</div>}
    </div>
  )
}
