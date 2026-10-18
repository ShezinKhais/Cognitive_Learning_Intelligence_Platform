import type { ReactNode } from 'react'
import { FlaskConical } from 'lucide-react'

/** Marks everything inside it as a working preview on made-up data, so
 * nobody takes it for a real class. */
export default function DemoFrame({ children, note }: { children: ReactNode; note?: string }) {
  return (
    <section aria-label="Demo" className="rounded-lg border-2 border-dashed border-input bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-dashed border-input px-5 py-2.5 text-sm">
        <FlaskConical size={16} aria-hidden className="text-muted-foreground" />
        <strong>Demo with sample data.</strong>
        <span className="text-muted-foreground">{note ?? 'Nothing here is a real student or class, and nothing is saved.'}</span>
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}
