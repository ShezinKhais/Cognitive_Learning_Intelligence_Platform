import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check } from 'lucide-react'

import { buttonStyles } from '../../components/ui/button'
import DemoFrame from './DemoFrame'

const NEEDS = [
  { key: 'camera', label: 'I cannot use a camera in class', effect: 'Attention will not read your camera at all.' },
  { key: 'gaze', label: 'Eye-tracking does not work for me', effect: 'Where you look is never counted.' },
  { key: 'pace', label: 'I need more time to answer', effect: 'How fast you answer is never counted.' },
  { key: 'prompts', label: 'Check-in prompts disrupt me', effect: 'You will not get private check-in prompts.' },
] as const

const STEPS = ['What you need', 'For how long', 'Check and send'] as const

/** A student asking for special consideration, step by step. An
 * accommodated student is never prompted or marked disengaged; this is how
 * they would ask for it. */
export default function ConsiderationDemo() {
  const [step, setStep] = useState(0)
  const [needs, setNeeds] = useState<Set<string>>(new Set())
  const [until, setUntil] = useState('end-of-term')
  const [sent, setSent] = useState(false)

  const chosen = NEEDS.filter((need) => needs.has(need.key))

  return (
    <DemoFrame note="Nothing is sent, and no one sees what you choose here.">
      <ol className="flex gap-2" aria-label="Steps">
        {STEPS.map((label, index) => (
          <li key={label} className="flex flex-1 items-center gap-2">
            <span
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border text-sm font-bold transition-colors ${
                index < step || sent ? 'border-success bg-success text-success-foreground' : index === step ? 'border-primary bg-primary text-primary-foreground' : 'border-input text-muted-foreground'
              }`}
            >
              {index < step || sent ? <Check size={14} aria-hidden /> : index + 1}
            </span>
            <span className={`hidden text-sm sm:inline ${index === step ? 'font-semibold' : 'text-muted-foreground'}`}>{label}</span>
          </li>
        ))}
      </ol>

      <div className="mt-6 min-h-56">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={sent ? 'sent' : step}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.18 }}
          >
            {sent ? (
              <div className="rounded-md border border-success/30 bg-success/5 px-5 py-6">
                <p className="text-lg font-bold">Sent to the administrator</p>
                <p className="mt-1 text-muted-foreground">
                  You will hear back by email. Until then, nothing about how C.L.I.P treats you changes.
                </p>
              </div>
            ) : step === 0 ? (
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
                  {[
                    ['end-of-term', 'Until the end of this term'],
                    ['four-weeks', 'For the next four weeks'],
                    ['ongoing', 'Ongoing, reviewed each year'],
                  ].map(([value, label]) => (
                    <label key={value} className={`flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 transition-colors ${until === value ? 'border-primary bg-accent' : 'border-border hover:bg-muted'}`}>
                      <input type="radio" name="until" value={value} checked={until === value} onChange={() => setUntil(value)} className="accent-[var(--primary)]" />
                      {label}
                    </label>
                  ))}
                </div>
                <p className="mt-3 text-sm text-muted-foreground">You do not have to say why. A document can help, but it is optional.</p>
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
                <p className="mt-3 text-sm text-muted-foreground">
                  Your lecturer is told only that you have an accommodation, never what it is.
                </p>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {!sent && (
        <div className="mt-4 flex justify-between gap-2">
          <button type="button" className={buttonStyles({ intent: 'quiet' })} disabled={step === 0} onClick={() => setStep((n) => n - 1)}>
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button type="button" className={buttonStyles()} disabled={step === 0 && needs.size === 0} onClick={() => setStep((n) => n + 1)}>
              Next
            </button>
          ) : (
            <button type="button" className={buttonStyles()} onClick={() => setSent(true)}>
              Send request
            </button>
          )}
        </div>
      )}
    </DemoFrame>
  )
}
