import { useEffect, useState } from 'react'

import { Panel } from '../../components/ui/primitives'
import SessionStrip, { StripLegend } from '../sessions/SessionStrip'
import { listAllResponses, type SessionResponse } from '../sessions/sessionsApi'
import { stripFromResponses } from '../sessions/strip'

/**
 * How the class has answered so far, from the stored responses: one tick per
 * question. Re-read whenever a question closes, and every few seconds while
 * one is open, so it fills in as answers arrive.
 */
export default function LiveResults({
  sessionId,
  openQuestionId,
  closedQuestionId,
}: {
  sessionId: string
  openQuestionId: string | null
  closedQuestionId: string | null
}) {
  const [responses, setResponses] = useState<SessionResponse[] | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => listAllResponses(sessionId).then((found) => !cancelled && setResponses(found), () => undefined)
    void load()
    const timer = openQuestionId ? window.setInterval(load, 4000) : undefined
    return () => {
      cancelled = true
      if (timer) window.clearInterval(timer)
    }
  }, [sessionId, openQuestionId, closedQuestionId])

  const strip = stripFromResponses(responses ?? [])
  const last = strip[strip.length - 1]

  return (
    <Panel title="How the class is answering" description="One tick per question, filled by how the answers went.">
      {responses === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : strip.length === 0 ? (
        <p className="text-sm text-muted-foreground">Answers appear here as soon as the first question is sent.</p>
      ) : (
        <>
          <SessionStrip questions={strip} />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <StripLegend />
            {last && (
              <p className="text-sm">
                Latest: <strong>{last.right + last.wrong + last.unmarked}</strong> answers,{' '}
                <strong>{last.right}</strong> right
              </p>
            )}
          </div>
        </>
      )}
    </Panel>
  )
}
