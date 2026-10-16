import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { getMaterial } from './materialApi'
import type { Material } from './types'
import { formatBytes, materialWarnings, sourceName } from './upload'

/** What C.L.I.P read from a material, opened under its row: the pages, and
 * anything worth checking before approving the questions drawn from them. */
export default function MaterialDetails({ material }: { material: Material }) {
  const [full, setFull] = useState<Material | null>(material.pages ? material : null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (material.pages) return
    let cancelled = false
    getMaterial(material.id).then(
      (found) => !cancelled && setFull(found),
      () => !cancelled && setFailed(true),
    )
    return () => {
      cancelled = true
    }
  }, [material])

  const shown = full ?? material
  const label = sourceName(shown)
  const warnings = materialWarnings(shown)
  const pages = shown.pages ?? []
  const [selected, setSelected] = useState(0)
  const page = pages[Math.min(selected, pages.length - 1)]

  return (
    <div className="grid gap-6 border-t border-border bg-background/60 px-5 py-5 lg:grid-cols-[1fr_17rem]">
      <div className="min-w-0">
        {!full && !failed && <p className="text-sm text-muted-foreground">Loading what was read from it…</p>}
        {failed && <p className="text-sm text-critical">The pages could not be loaded.</p>}
        {full && pages.length === 0 && (
          <p className="text-sm text-muted-foreground">No page text has been read from this material yet.</p>
        )}
        {page && (
          <>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label={`${label}s`}>
              {pages.map((item, index) => (
                <button
                  key={`${item.page_number}-${index}`}
                  type="button"
                  role="tab"
                  aria-selected={index === selected}
                  onClick={() => setSelected(index)}
                  className={`min-w-9 rounded px-2 py-1 text-sm transition-colors ${
                    index === selected
                      ? 'bg-primary font-semibold text-primary-foreground'
                      : item.is_thin || item.is_visual_heavy
                        ? 'bg-warning/10 text-warning hover:bg-warning/20'
                        : 'bg-muted hover:bg-accent'
                  }`}
                  title={item.is_thin ? 'Little text' : item.is_visual_heavy ? 'Mostly images' : undefined}
                >
                  {item.page_number}
                </button>
              ))}
            </div>
            <div role="tabpanel" className="mt-3 rounded-md border border-border bg-card px-4 py-3">
              <p className="text-sm font-semibold">
                {label} {page.page_number}
                {page.word_count != null && (
                  <span className="font-normal text-muted-foreground">, {page.word_count} words</span>
                )}
              </p>
              <p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-sm leading-6">
                {page.text || 'No readable text was found here.'}
              </p>
            </div>
          </>
        )}
      </div>

      <aside className="space-y-5 text-sm">
        <dl className="space-y-1.5">
          <Fact label={`${label}s`} value={shown.page_count ?? 'Not counted yet'} />
          <Fact label="Sections for the tutor" value={shown.chunk_count ?? 'Not split yet'} />
          <Fact label="File size" value={formatBytes(shown.size_bytes)} />
        </dl>
        <div>
          <p className="font-semibold">{warnings.length ? 'Worth checking' : 'Nothing to check'}</p>
          {warnings.length > 0 && (
            <ul className="mt-2 space-y-2">
              {warnings.map((warning, index) => (
                <li key={`${warning.code ?? 'w'}-${warning.source_page ?? index}`} className="flex gap-2">
                  <AlertTriangle size={15} aria-hidden className="mt-0.5 shrink-0 text-warning" />
                  <span>
                    {warning.source_page !== undefined && (
                      <button type="button" className="font-semibold underline-offset-2 hover:underline" onClick={() => setSelected(Math.max(0, pages.findIndex((p) => p.page_number === warning.source_page)))}>
                        {label} {warning.source_page}:{' '}
                      </button>
                    )}
                    <span className="text-muted-foreground">{warning.message}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  )
}
