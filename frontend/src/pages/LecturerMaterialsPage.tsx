import {
  useCallback,
  useRef,
  useState,
} from 'react'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  LogOut,
  RotateCcw,
  UploadCloud,
  Wifi,
  WifiOff,
} from 'lucide-react'

import {
  ApiError,
  clearAccessToken,
} from '../api'
import {
  getMaterial,
  uploadMaterial,
} from '../features/materials/materialApi'
import type {
  Material,
  MaterialPagePreview,
  MaterialProgress,
  MaterialStage,
  MaterialWarning,
  ProgressConnectionStatus,
} from '../features/materials/types'
import { PROCESSING_STAGES } from '../features/materials/types'
import { useMaterialProgress } from '../features/materials/useMaterialProgress'

const ACCEPTED_EXTENSIONS = ['pdf', 'pptx', 'docx', 'txt']
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

interface LocalFile {
  name: string
  size: number
  type: string
}

function fileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

function validateUpload(file: File): string | null {
  const extension = fileExtension(file.name)

  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return 'Choose a PDF, PowerPoint, Word or plain-text file.'
  }

  if (file.size === 0) return 'The selected file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) return 'The selected file is larger than 50 MB.'

  return null
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function initialProgress(material: Material): MaterialProgress {
  if (material.status === 'completed') {
    return {
      material_id: material.id,
      stage: 'done',
      percent: 100,
      message: 'Processing complete.',
    }
  }

  if (material.status === 'failed') {
    return {
      material_id: material.id,
      stage: 'failed',
      percent: 100,
      message: material.error ?? 'Processing failed.',
    }
  }

  return {
    material_id: material.id,
    stage: 'validating',
    percent: 5,
    message: 'Upload accepted. Waiting for processing to begin.',
  }
}

export default function LecturerMaterialsPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const activeMaterialId = useRef<string | null>(null)
  const [localFile, setLocalFile] = useState<LocalFile | null>(null)
  const [material, setMaterial] = useState<Material | null>(null)
  const [progress, setProgress] = useState<MaterialProgress | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshMaterial = useCallback(async (materialId: string) => {
    try {
      const refreshed = await getMaterial(materialId)
      setMaterial(refreshed)
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) {
        clearAccessToken()
        window.location.assign('/login')
        return
      }

      // BBIS owns this query and may not have connected it yet. The progress
      // event remains authoritative, so a missing refresh must not turn a
      // successfully processed upload into an error on screen.
    }
  }, [])

  const receiveProgress = useCallback((next: MaterialProgress) => {
    if (next.material_id !== activeMaterialId.current) return

    setProgress(next)

    if (next.stage === 'failed') {
      setError(next.message ?? 'The material could not be processed.')
    } else if (next.stage === 'done') {
      setError(null)
      void refreshMaterial(next.material_id)
    }
  }, [refreshMaterial])

  const connectionStatus = useMaterialProgress(receiveProgress)

  async function handleFile(file: File) {
    const validationMessage = validateUpload(file)
    const nextLocalFile = {
      name: file.name,
      size: file.size,
      type: file.type,
    }

    setLocalFile(nextLocalFile)
    setMaterial(null)
    setProgress(null)
    setError(validationMessage)
    activeMaterialId.current = null

    if (validationMessage) return

    setUploading(true)

    try {
      const uploaded = await uploadMaterial(file)
      activeMaterialId.current = uploaded.id
      setMaterial(uploaded)
      setProgress(initialProgress(uploaded))
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 401) {
        clearAccessToken()
        window.location.assign('/login')
        return
      }

      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Upload failed. Check your connection and try again.',
      )
    } finally {
      setUploading(false)
    }
  }

  function onInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) void handleFile(file)
    event.target.value = ''
  }

  function resetUpload() {
    activeMaterialId.current = null
    setLocalFile(null)
    setMaterial(null)
    setProgress(null)
    setError(null)
  }

  return (
    <main className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              C.L.I.P lecturer workspace
            </p>
            <h1 className="mt-1 text-xl font-bold text-card-foreground">
              Lecture materials
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <ConnectionBadge status={connectionStatus} />
            <button
              type="button"
              onClick={() => {
                clearAccessToken()
                window.location.assign('/login')
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              <LogOut aria-hidden="true" size={16} />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
        <div className="max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight">
            Prepare grounded questions from your content
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Upload one lecture file. C.L.I.P extracts its content, preserves page or slide
            references and reports anything that may need your attention.
          </p>
        </div>

        {!localFile ? (
          <UploadDropzone
            inputRef={inputRef}
            uploading={uploading}
            onInputChange={onInputChange}
            onFile={handleFile}
          />
        ) : (
          <div className="mt-8 space-y-6">
            <FileSummary
              file={localFile}
              uploading={uploading}
              onReset={resetUpload}
            />

            {error && <ErrorNotice message={error} />}

            {(uploading || progress) && (
              <ProcessingStatus
                uploading={uploading}
                progress={progress}
                connectionStatus={connectionStatus}
              />
            )}

            {material && (
              <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
                <ContentPreview
                  material={material}
                  stage={progress?.stage ?? null}
                />
                <MaterialInsights
                  material={material}
                  stage={progress?.stage ?? null}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  )
}

function ConnectionBadge({ status }: { status: ProgressConnectionStatus }) {
  const connected = status === 'connected'

  return (
    <div
      className={`hidden items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium sm:flex ${
        connected
          ? 'bg-success/10 text-success'
          : 'bg-muted text-muted-foreground'
      }`}
      title="Live processing progress connection"
    >
      {connected
        ? <Wifi aria-hidden="true" size={14} />
        : <WifiOff aria-hidden="true" size={14} />}
      {connected
        ? 'Live updates on'
        : status === 'connecting'
          ? 'Connecting...'
          : 'Reconnecting...'}
    </div>
  )
}

function UploadDropzone({
  inputRef,
  uploading,
  onInputChange,
  onFile,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>
  uploading: boolean
  onInputChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  onFile: (file: File) => void
}) {
  const [dragging, setDragging] = useState(false)

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) onFile(file)
  }

  return (
    <section className="mt-8 rounded-2xl border border-border bg-card p-4 shadow-[var(--shadow-card)] sm:p-6">
      <div
        onDragEnter={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed px-5 py-12 text-center transition-colors ${
          dragging
            ? 'border-ring bg-accent'
            : 'border-border bg-background'
        }`}
      >
        <div className="mx-auto grid size-12 place-items-center rounded-xl bg-secondary text-secondary-foreground">
          <UploadCloud aria-hidden="true" size={24} />
        </div>
        <h3 className="mt-4 font-semibold">Drop your lecture material here</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          PDF, PPTX, DOCX or TXT · maximum 50 MB
        </p>
        <button
          type="button"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
          className="mt-6 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Choose file
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.pptx,.docx,.txt"
          className="hidden"
          onChange={onInputChange}
        />
      </div>
    </section>
  )
}

function FileSummary({
  file,
  uploading,
  onReset,
}: {
  file: LocalFile
  uploading: boolean
  onReset: () => void
}) {
  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex min-w-0 items-center gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-info/10 text-info">
          <FileText aria-hidden="true" size={20} />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-card-foreground">{file.name}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {formatBytes(file.size)} · {fileExtension(file.name).toUpperCase()}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onReset}
        disabled={uploading}
        className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
      >
        <RotateCcw aria-hidden="true" size={15} />
        Upload another
      </button>
    </section>
  )
}

function ProcessingStatus({
  uploading,
  progress,
  connectionStatus,
}: {
  uploading: boolean
  progress: MaterialProgress | null
  connectionStatus: ProgressConnectionStatus
}) {
  const stage: MaterialStage = uploading
    ? 'validating'
    : progress?.stage ?? 'validating'
  const percent = uploading ? 2 : Math.max(0, Math.min(progress?.percent ?? 0, 100))
  const failed = stage === 'failed'
  const completed = stage === 'done'
  const activeIndex = PROCESSING_STAGES.findIndex((item) => item.key === stage)

  return (
    <section
      className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)]"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold text-card-foreground">
            {failed
              ? 'Processing stopped'
              : completed
                ? 'Material ready'
                : uploading
                  ? 'Uploading material'
                  : 'Preparing material'}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {uploading
              ? 'Sending the file securely...'
              : progress?.message ?? 'Waiting for the next processing update...'}
          </p>
        </div>
        {failed
          ? <AlertCircle className="shrink-0 text-critical" aria-hidden="true" size={22} />
          : completed
            ? <CheckCircle2 className="shrink-0 text-success" aria-hidden="true" size={22} />
            : <LoaderCircle className="shrink-0 animate-spin text-info" aria-hidden="true" size={22} />}
      </div>

      <div className="mt-5 h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            failed ? 'bg-critical' : completed ? 'bg-success' : 'bg-info'
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>{failed ? 'Failed' : `${percent}% complete`}</span>
        {!completed && !failed && connectionStatus !== 'connected' && (
          <span>Live updates reconnecting</span>
        )}
      </div>

      {!failed && (
        <ol className="mt-6 grid grid-cols-3 gap-3 sm:grid-cols-6">
          {PROCESSING_STAGES.map((item, index) => {
            const done = completed || index < activeIndex
            const current = index === activeIndex && !completed

            return (
              <li key={item.key} className="min-w-0 text-center">
                <div
                  className={`mx-auto grid size-7 place-items-center rounded-full border text-xs ${
                    done
                      ? 'border-success bg-success text-success-foreground'
                      : current
                        ? 'border-info bg-info text-info-foreground'
                        : 'border-border bg-background text-muted-foreground'
                  }`}
                >
                  {done ? <Check aria-hidden="true" size={14} /> : index + 1}
                </div>
                <span className={`mt-1.5 block truncate text-[11px] ${
                  current ? 'font-semibold text-card-foreground' : 'text-muted-foreground'
                }`}>
                  {item.label}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-critical/20 bg-critical/10 p-4 text-critical" role="alert">
      <AlertCircle className="mt-0.5 shrink-0" aria-hidden="true" size={19} />
      <div>
        <p className="text-sm font-semibold">We could not finish this upload</p>
        <p className="mt-1 text-sm">{message}</p>
      </div>
    </div>
  )
}

function sourceName(material: Material): string {
  return fileExtension(material.filename) === 'pptx' ? 'Slide' : 'Page'
}

function ContentPreview({
  material,
  stage,
}: {
  material: Material
  stage: MaterialStage | null
}) {
  const pages = material.pages ?? []
  const completed = stage === 'done' || material.status === 'completed'

  return (
    <section className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold text-card-foreground">Extracted content</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Review the text C.L.I.P will use to ground its questions.
          </p>
        </div>
        {material.page_count !== null && (
          <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
            {material.page_count} {sourceName(material).toLowerCase()}{material.page_count === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {pages.length > 0 ? (
        <div className="mt-5 space-y-3">
          {pages.map((page, index) => (
            <PagePreview
              key={`${page.page_number}-${index}`}
              page={page}
              sourceLabel={sourceName(material)}
              expanded={index === 0}
            />
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-lg border border-dashed border-border bg-background px-5 py-10 text-center">
          <FileText className="mx-auto text-muted-foreground" aria-hidden="true" size={25} />
          <p className="mt-3 text-sm font-medium">
            {completed ? 'No extracted preview was returned' : 'Preview appears after extraction'}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
            {completed
              ? 'The material finished processing, but the page-content API has not supplied its preview yet.'
              : 'You can leave this screen open while the remaining processing steps continue.'}
          </p>
        </div>
      )}
    </section>
  )
}

function PagePreview({
  page,
  sourceLabel,
  expanded,
}: {
  page: MaterialPagePreview
  sourceLabel: string
  expanded: boolean
}) {
  return (
    <details className="group rounded-lg border border-border bg-background" open={expanded}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-4 py-3">
        <span className="text-sm font-semibold">
          {sourceLabel} {page.page_number}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {page.word_count !== undefined && (
            <span className="text-xs text-muted-foreground">{page.word_count} words</span>
          )}
          {page.is_thin && (
            <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">
              Thin content
            </span>
          )}
          {page.is_image_heavy && (
            <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">
              <ImageIcon aria-hidden="true" size={11} /> Image-heavy
            </span>
          )}
        </span>
      </summary>
      <div className="border-t border-border px-4 py-4">
        <p className="whitespace-pre-wrap text-sm leading-6 text-card-foreground">
          {page.text || 'No readable text was extracted from this source.'}
        </p>
      </div>
    </details>
  )
}

function normaliseWarnings(material: Material): MaterialWarning[] {
  const supplied = (material.warnings ?? []).map((warning) =>
    typeof warning === 'string'
      ? { message: warning, severity: 'warning' as const }
      : warning,
  )

  const pageWarnings = (material.pages ?? []).flatMap((page) => {
    const warnings: MaterialWarning[] = []

    if (page.is_thin) {
      warnings.push({
        code: 'THIN_CONTENT',
        message: 'Very little readable text was extracted from this source.',
        severity: 'warning',
        source_page: page.page_number,
      })
    }

    if (page.is_image_heavy) {
      warnings.push({
        code: 'IMAGE_HEAVY',
        message: 'This source relies heavily on images; check the extracted text before generating questions.',
        severity: 'warning',
        source_page: page.page_number,
      })
    }

    return warnings
  })

  return [...supplied, ...pageWarnings]
}

function MaterialInsights({
  material,
  stage,
}: {
  material: Material
  stage: MaterialStage | null
}) {
  const warnings = normaliseWarnings(material)
  const label = sourceName(material)
  const checksComplete = stage === 'done' || material.status === 'completed'

  return (
    <aside className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <h3 className="font-semibold text-card-foreground">Source summary</h3>
        <dl className="mt-4 space-y-3">
          <SummaryRow label="Format" value={fileExtension(material.filename).toUpperCase()} />
          <SummaryRow label="File size" value={formatBytes(material.size_bytes)} />
          <SummaryRow label={`${label}s found`} value={material.page_count ?? '—'} />
          <SummaryRow label="Content chunks" value={material.chunk_count ?? '—'} />
        </dl>
      </section>

      <section className="rounded-xl border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold text-card-foreground">Content checks</h3>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            warnings.length
              ? 'bg-warning/10 text-warning'
              : checksComplete
                ? 'bg-success/10 text-success'
                : 'bg-muted text-muted-foreground'
          }`}>
            {warnings.length
              ? `${warnings.length} warning${warnings.length === 1 ? '' : 's'}`
              : checksComplete
                ? 'No warnings'
                : 'Checks pending'}
          </span>
        </div>

        {warnings.length ? (
          <ul className="mt-4 space-y-3">
            {warnings.map((warning, index) => (
              <li key={`${warning.code ?? 'warning'}-${warning.source_page ?? index}`} className="flex items-start gap-2.5">
                <AlertTriangle className="mt-0.5 shrink-0 text-warning" aria-hidden="true" size={16} />
                <div>
                  {warning.source_page !== undefined && (
                    <p className="text-xs font-semibold text-card-foreground">
                      {label} {warning.source_page}
                    </p>
                  )}
                  <p className="text-xs leading-5 text-muted-foreground">{warning.message}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : checksComplete ? (
          <div className="mt-4 flex items-start gap-2.5 text-success">
            <CheckCircle2 className="mt-0.5 shrink-0" aria-hidden="true" size={17} />
            <p className="text-xs leading-5">
              No extraction warnings have been reported for this material.
            </p>
          </div>
        ) : (
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Thin-content and image-heavy source checks will appear after extraction.
          </p>
        )}
      </section>
    </aside>
  )
}

function SummaryRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-card-foreground">{value}</dd>
    </div>
  )
}
