import { useEffect, useId, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check } from 'lucide-react'

import { ApiError } from '../api'
import { buttonStyles } from '../components/ui/button'
import { MetaLine, PageBody, PageHeader, Panel, SkeletonRows, Tag, type Tone } from '../components/ui/primitives'
import {
  getMyRequest,
  NEED_LABEL,
  NEEDS,
  sendRequest,
  untilLabel,
  withdrawRequest,
  type ConsiderationNeed,
  type ConsiderationRequest,
  type ConsiderationStatus,
} from '../features/consideration/considerationApi'
import { sinceVerb } from '../features/format/relativeTime'

const STEPS = ['What you need', 'For how long', 'Check and send'] as const
const STATUS: Record<ConsiderationStatus, { word: string; tone: Tone }> = {
  pending: { word: 'Waiting for a decision', tone: 'info' },
  approved: { word: 'Approved', tone: 'good' },
  rejected: { word: 'Not approved', tone: 'poor' },
  withdrawn: { word: 'Withdrawn', tone: 'neutral' },
}

type Until = 'term' | 'four-weeks' | 'date'

function isoDay(offsetDays: number): string {
  const day = new Date()
  day.setDate(day.getDate() + offsetDays)
  // Local year, month and day: toISOString is UTC, a day behind before 04:00 here.
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

/** Asking C.L.I.P to treat you differently in class. Decided by an
 * administrator; the lecturer only learns that an accommodation exists. */
export default function StudentConsiderationPage() {
  const [current, setCurrent] = useState<ConsiderationRequest | null | undefined>(undefined)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMyRequest().then(
      (mine) => setCurrent(mine.current),
      () => setError('Your request could not be loaded. Check your connection and reload.'),
    )
  }, [])

  const showForm = asking || current === null || current?.status === 'withdrawn'

  return (
    <>
      <PageHeader
        title="Special consideration"
        description="Ask for C.L.I.P to treat you differently in class, without having to explain why to your lecturer."
      />
      <PageBody>
        {error && <p role="alert" className="mb-4 text-critical">{error}</p>}
        {current === undefined && !error ? (
          <SkeletonRows label="Loading your request" rows={1} />
        ) : showForm ? (
          <RequestForm
            onSent={(sent) => {
              setCurrent(sent)
              setAsking(false)
            }}
            onCancel={current && current.status !== 'withdrawn' ? () => setAsking(false) : undefined}
          />
        ) : current ? (
          <CurrentRequest
            request={current}
            onWithdrawn={setCurrent}
            onAskAgain={() => setAsking(true)}
          />
        ) : null}
      </PageBody>
    </>
  )
}

function CurrentRequest({
  request,
  onWithdrawn,
  onAskAgain,
}: {
  request: ConsiderationRequest
  onWithdrawn: (request: ConsiderationRequest) => void
  onAskAgain: () => void
}) {
  const [busy, setBusy] = useState(false)
  const status = STATUS[request.status]
  return (
    <Panel
      title="Your request"
      description={sinceVerb('Sent', request.created_at)}
      actions={<Tag tone={status.tone}>{status.word}</Tag>}
      className="max-w-2xl"
    >
      <ul className="space-y-1.5">
        {request.needs.map((need) => (
          <li key={need} className="flex gap-2">
            <Check size={16} aria-hidden className="mt-1 text-success" />
            {NEED_LABEL[need]}
          </li>
        ))}
      </ul>
      <MetaLine className="mt-3" items={[untilLabel(request.until), request.note ? 'With a note for the administrator' : null]} />
      {request.decision_note && (
        <p className="mt-4 rounded-md bg-muted px-4 py-3 text-sm">
          <span className="font-semibold">From the administrator: </span>
          {request.decision_note}
        </p>
      )}
      <p className="mt-4 text-sm text-muted-foreground">
        {request.status === 'approved'
          ? 'You are never sent check-in prompts and never marked disengaged. Your lecturer sees only that you have an accommodation.'
          : request.status === 'pending'
            ? 'Until it is decided, nothing about how C.L.I.P treats you changes.'
            : 'Nothing about how C.L.I.P treats you has changed. You can ask again.'}
      </p>
      <div className="mt-4 flex gap-2">
        {request.status === 'pending' ? (
          <button
            type="button"
            className={buttonStyles({ intent: 'secondary' })}
            disabled={busy}
            onClick={() => {
              setBusy(true)
              withdrawRequest().then(onWithdrawn, () => setBusy(false))
            }}
          >
            {busy ? 'Withdrawing…' : 'Withdraw the request'}
          </button>
        ) : (
          <button type="button" className={buttonStyles({ intent: 'secondary' })} onClick={onAskAgain}>
            {request.status === 'approved' ? 'Ask for something else' : 'Ask again'}
          </button>
        )}
      </div>
    </Panel>
  )
}

function RequestForm({ onSent, onCancel }: { onSent: (sent: ConsiderationRequest) => void; onCancel?: () => void }) {
  const [step, setStep] = useState(0)
  const [needs, setNeeds] = useState<Set<ConsiderationNeed>>(new Set())
  const [until, setUntil] = useState<Until>('term')
  const [date, setDate] = useState(isoDay(28))
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const noteId = useId()

  const chosen = NEEDS.filter((need) => needs.has(need.key))
  const lastDay = until === 'term' ? null : until === 'four-weeks' ? isoDay(28) : date

  function send() {
    setSending(true)
    setError(null)
    sendRequest({ needs: [...needs], until: lastDay, note: note.trim() || null }).then(onSent, (caught: unknown) => {
      setSending(false)
      setError(caught instanceof ApiError ? caught.message : 'The request could not be sent. Try again.')
    })
  }

  return (
    <Panel className="max-w-3xl">
      <ol className="flex gap-2" aria-label="Steps">
        {STEPS.map((label, index) => (
          <li key={label} className="flex flex-1 items-center gap-2" aria-current={index === step ? 'step' : undefined}>
            <span
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border text-sm font-bold transition-colors ${
                index < step ? 'border-success bg-success text-success-foreground' : index === step ? 'border-primary bg-primary text-primary-foreground' : 'border-input text-muted-foreground'
              }`}
            >
              {index < step ? <Check size={14} aria-hidden /> : index + 1}
            </span>
            <span className={`hidden text-sm sm:inline ${index === step ? 'font-semibold' : 'text-muted-foreground'}`}>{label}</span>
          </li>
        ))}
      </ol>

      <div className="mt-6 min-h-56">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.18 }}
          >
            {step === 0 ? (
              <fieldset>
                <legend className="font-semibold">Choose anything that applies</legend>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {NEEDS.map((need) => {
                    const on = needs.has(need.key)
                    return (
                      <label
                        key={need.key}
                        className={`flex cursor-pointer gap-3 rounded-md border px-4 py-3 transition-colors ${on ? 'border-primary bg-accent' : 'border-border hover:bg-muted'}`}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() =>
                            setNeeds((current) => {
                              const next = new Set(current)
                              if (next.has(need.key)) next.delete(need.key)
                              else next.add(need.key)
                              return next
                            })
                          }
                          className="mt-1 accent-[var(--primary)]"
                        />
                        <span>
                          <span className="block font-semibold">{need.label}</span>
                          <span className="block text-sm text-muted-foreground">{need.effect}</span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              </fieldset>
            ) : step === 1 ? (
              <fieldset>
                <legend className="font-semibold">How long do you need it?</legend>
                <div className="mt-3 grid gap-2">
                  {(
                    [
                      ['term', 'Until the end of this term'],
                      ['four-weeks', 'For the next four weeks'],
                      ['date', 'Until a date I choose'],
                    ] as const
                  ).map(([value, label]) => (
                    <label
                      key={value}
                      className={`flex cursor-pointer flex-wrap items-center gap-3 rounded-md border px-4 py-3 transition-colors ${until === value ? 'border-primary bg-accent' : 'border-border hover:bg-muted'}`}
                    >
                      <input type="radio" name="until" value={value} checked={until === value} onChange={() => setUntil(value)} className="accent-[var(--primary)]" />
                      {label}
                      {value === 'date' && until === 'date' && (
                        <input
                          type="date"
                          aria-label="Last day"
                          value={date}
                          min={isoDay(0)}
                          max={isoDay(365)}
                          onChange={(event) => setDate(event.target.value)}
                          className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                        />
                      )}
                    </label>
                  ))}
                </div>
                <label htmlFor={noteId} className="mt-5 block text-sm font-semibold">
                  Anything the administrator should know <span className="font-normal text-muted-foreground">(optional)</span>
                </label>
                <textarea
                  id={noteId}
                  value={note}
                  maxLength={500}
                  rows={3}
                  onChange={(event) => setNote(event.target.value)}
                  className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm"
                  placeholder="You do not have to say why."
                />
                <p className="mt-1 text-xs text-muted-foreground">Only administrators read this. Your lecturer never does.</p>
              </fieldset>
            ) : (
              <div>
                <p className="font-semibold">You are asking for:</p>
                <ul className="mt-2 space-y-1.5">
                  {chosen.map((need) => (
                    <li key={need.key} className="flex gap-2">
                      <Check size={16} aria-hidden className="mt-1 text-success" />
                      <span>
                        {need.label}. <span className="text-muted-foreground">{need.effect}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-sm">{untilLabel(lastDay)}.</p>
                <p className="mt-3 text-sm text-muted-foreground">
                  Your lecturer is told only that you have an accommodation, never what it is.
                </p>
                {error && <p role="alert" className="mt-3 text-sm text-critical">{error}</p>}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="mt-4 flex justify-between gap-2">
        <button
          type="button"
          className={buttonStyles({ intent: 'quiet' })}
          disabled={(step === 0 && !onCancel) || sending}
          onClick={() => (step === 0 ? onCancel?.() : setStep((n) => n - 1))}
        >
          {step === 0 ? 'Cancel' : 'Back'}
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" className={buttonStyles()} disabled={(step === 0 && needs.size === 0) || (step === 1 && until === 'date' && !date)} onClick={() => setStep((n) => n + 1)}>
            Next
          </button>
        ) : (
          <button type="button" className={buttonStyles()} disabled={sending} onClick={send}>
            {sending ? 'Sending…' : 'Send request'}
          </button>
        )}
      </div>
    </Panel>
  )
}
