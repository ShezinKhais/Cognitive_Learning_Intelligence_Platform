import { useState } from 'react'
import { Download } from 'lucide-react'

import { ApiError, authenticatedFetch } from '../../api'
import { buttonStyles } from '../../components/ui/button'
import type { QuestionBreakdown, StudentBreakdown } from './sessionsApi'

const percent = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : '–')

/** Each question in the order it was asked, with how the choices split. */
export function QuestionTable({ questions }: { questions: QuestionBreakdown[] }) {
  if (questions.length === 0) return <p className="text-muted-foreground">No question was asked in this session.</p>
  return (
    <ol className="divide-y divide-border">
      {questions.map((question) => (
        <li key={question.question_id} className="py-4 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="min-w-0 font-semibold">
              <span className="text-muted-foreground">{question.number}. </span>
              {question.prompt}
            </p>
            <p className="shrink-0 text-sm text-muted-foreground">
              {question.answers} of {question.eligible} answered
              {question.marked > 0 && `, ${percent(question.correct, question.marked)} right`}
              {question.median_seconds !== null && `, ${question.median_seconds.toFixed(0)}s typical`}
            </p>
          </div>
          {question.options && question.option_counts && (
            <ul className="mt-2 space-y-1.5">
              {question.options.map((option, index) => {
                const chosen = question.option_counts?.[index] ?? 0
                const right = index === question.correct_option
                return (
                  <li key={index} className="grid grid-cols-[minmax(0,1fr)_8rem_3rem] items-center gap-3 text-sm">
                    <span className={right ? 'font-semibold text-success' : undefined}>
                      {option}
                      {right && <span className="sr-only"> (correct)</span>}
                    </span>
                    <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                      <span
                        className={`block h-full ${right ? 'bg-success' : 'bg-muted-foreground/40'}`}
                        style={{ width: question.answers ? `${(chosen / question.answers) * 100}%` : '0%' }}
                      />
                    </span>
                    <span className="text-right tabular-nums text-muted-foreground">{chosen}</span>
                  </li>
                )
              })}
            </ul>
          )}
        </li>
      ))}
    </ol>
  )
}

/** Each student who answered or missed a question. */
export function StudentTable({ students }: { students: StudentBreakdown[] }) {
  if (students.length === 0) return <p className="text-muted-foreground">No student answered in this session.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th scope="col" className="py-2 pr-4 font-medium">Student</th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">Answered</th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">Right</th>
            <th scope="col" className="py-2 text-right font-medium">Missed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {students.map((student) => (
            <tr key={student.student_id}>
              <th scope="row" className="py-2 pr-4 text-left font-semibold">{student.name}</th>
              <td className="py-2 pr-4 text-right tabular-nums">{student.answered}</td>
              <td className="py-2 pr-4 text-right tabular-nums">
                {student.marked ? `${student.correct} (${percent(student.correct, student.marked)})` : '–'}
              </td>
              <td className="py-2 text-right tabular-nums">{student.missed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Downloads every answer as a CSV. The file needs the sign-in, so it is
 * fetched and handed to the browser rather than linked. */
export function DownloadResults({ sessionId, title }: { sessionId: string; title: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const response = await authenticatedFetch(`/sessions/${encodeURIComponent(sessionId)}/results.csv`)
      if (!response.ok) throw new ApiError(response.status, 'DOWNLOAD_FAILED', 'The results could not be downloaded.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `${title.replace(/[^\w -]+/g, '').trim() || 'session'} results.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The results could not be downloaded.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className={buttonStyles({ intent: 'secondary' })} disabled={busy} onClick={() => void download()}>
        <Download size={16} aria-hidden />
        {busy ? 'Preparing…' : 'Download CSV'}
      </button>
      {error && (
        <p role="alert" className="basis-full text-sm text-critical">
          {error}
        </p>
      )}
    </>
  )
}
