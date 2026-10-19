import { describeQuestion, type StripQuestion } from './strip'

/**
 * The session as a row of ticks, one per question, like margin marks on a
 * page of lecture notes. Each tick fills from the bottom with the share of
 * the class that got it right, red above it for wrong, and a hatch for free
 * text still being marked. Every tick is labelled in words for screen
 * readers and on hover.
 */
export default function SessionStrip({
  questions,
  size = 'regular',
}: {
  questions: readonly StripQuestion[]
  size?: 'compact' | 'regular'
}) {
  if (questions.length === 0) return null
  const height = size === 'compact' ? 'h-6' : 'h-12'
  const width = size === 'compact' ? 'w-2' : 'w-3.5'
  return (
    <ol className="flex items-end gap-1" aria-label="How the class answered each question">
      {questions.map((question) => {
        const total = question.right + question.wrong + question.unmarked
        const pct = (n: number) => `${total === 0 ? 0 : (n / total) * 100}%`
        return (
          <li
            key={question.questionId}
            title={describeQuestion(question)}
            className={`relative flex ${height} ${width} flex-col-reverse overflow-hidden rounded-sm bg-muted`}
          >
            <span className="sr-only">{describeQuestion(question)}</span>
            <span aria-hidden className="block bg-success" style={{ height: pct(question.right) }} />
            <span aria-hidden className="block bg-critical/80" style={{ height: pct(question.wrong) }} />
            <span
              aria-hidden
              className="block bg-[repeating-linear-gradient(135deg,var(--muted-foreground)_0_1px,transparent_1px_4px)] opacity-60"
              style={{ height: pct(question.unmarked) }}
            />
          </li>
        )
      })}
    </ol>
  )
}

export function StripLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-success" /> Right
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-critical/80" /> Wrong
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden
          className="h-2.5 w-2.5 rounded-sm bg-[repeating-linear-gradient(135deg,var(--muted-foreground)_0_1px,transparent_1px_4px)]"
        />
        Not marked yet
      </span>
    </div>
  )
}
