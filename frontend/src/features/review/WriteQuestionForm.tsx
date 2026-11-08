import { useId, useState, type FormEvent } from 'react'
import { Plus, X } from 'lucide-react'

import { ApiError, writeQuestion, type Difficulty, type Question, type QuestionType } from '../../api'
import { buttonStyles } from '../../components/ui/button'

const FIELD = 'mt-1 w-full rounded-md border border-input bg-input-background px-3 py-2'

/** A question the lecturer writes themselves. It is ready to send once saved. */
export default function WriteQuestionForm({
  materialId,
  onCancel,
  onSaved,
}: {
  materialId: string
  onCancel: () => void
  onSaved: (question: Question) => void
}) {
  const id = useId()
  const [type, setType] = useState<QuestionType>('mcq')
  const [prompt, setPrompt] = useState('')
  const [options, setOptions] = useState(['', ''])
  const [correct, setCorrect] = useState(0)
  const [difficulty, setDifficulty] = useState<Difficulty>('medium')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!prompt.trim()) return setError('Write the question first.')
    const filled = options.map((option) => option.trim())
    if (type === 'mcq' && (filled.some((option) => !option) || new Set(filled).size !== filled.length)) {
      return setError('Fill in every option, each one different.')
    }
    setSaving(true)
    setError(null)
    writeQuestion(materialId, {
      type,
      prompt: prompt.trim(),
      difficulty,
      ...(type === 'mcq' ? { options: filled, correct_option: correct } : {}),
    }).then(onSaved, (caught: unknown) => {
      setSaving(false)
      setError(caught instanceof ApiError ? caught.message : 'The question could not be saved.')
    })
  }

  return (
    <form onSubmit={submit} className="mb-6 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="font-bold">Write a question</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">It is ready to send as soon as you save it.</p>

      <fieldset className="mt-3 flex gap-4 text-sm">
        <legend className="sr-only">Question type</legend>
        {(['mcq', 'free_text'] as const).map((kind) => (
          <label key={kind} className="flex items-center gap-2">
            <input type="radio" name={`${id}-type`} checked={type === kind} onChange={() => setType(kind)} />
            {kind === 'mcq' ? 'Multiple choice' : 'Written answer'}
          </label>
        ))}
      </fieldset>

      <label htmlFor={`${id}-prompt`} className="mt-3 block text-sm font-semibold">
        Question
      </label>
      <textarea
        id={`${id}-prompt`}
        rows={2}
        maxLength={1000}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        className={FIELD}
      />

      {type === 'mcq' && (
        <fieldset className="mt-3">
          <legend className="text-sm font-semibold">Options, with the correct one selected</legend>
          <ul className="mt-1 space-y-2">
            {options.map((option, index) => (
              <li key={index} className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`${id}-correct`}
                  aria-label={`Option ${index + 1} is correct`}
                  checked={correct === index}
                  onChange={() => setCorrect(index)}
                />
                <input
                  aria-label={`Option ${index + 1}`}
                  value={option}
                  maxLength={300}
                  onChange={(event) =>
                    setOptions((current) => current.map((item, at) => (at === index ? event.target.value : item)))
                  }
                  className="w-full rounded-md border border-input bg-input-background px-3 py-1.5"
                />
                {options.length > 2 && (
                  <button
                    type="button"
                    aria-label={`Remove option ${index + 1}`}
                    className={buttonStyles({ intent: 'quiet' })}
                    onClick={() => {
                      setOptions((current) => current.filter((_, at) => at !== index))
                      setCorrect((current) => (current === index ? 0 : current > index ? current - 1 : current))
                    }}
                  >
                    <X size={14} aria-hidden />
                  </button>
                )}
              </li>
            ))}
          </ul>
          {options.length < 6 && (
            <button
              type="button"
              className={buttonStyles({ intent: 'quiet', className: 'mt-2' })}
              onClick={() => setOptions((current) => [...current, ''])}
            >
              <Plus size={14} aria-hidden />
              Add an option
            </button>
          )}
        </fieldset>
      )}

      <label htmlFor={`${id}-difficulty`} className="mt-3 block text-sm font-semibold">
        Difficulty
      </label>
      <select
        id={`${id}-difficulty`}
        value={difficulty}
        onChange={(event) => setDifficulty(event.target.value as Difficulty)}
        className={`${FIELD} max-w-xs`}
      >
        <option value="easy">Easy</option>
        <option value="medium">Medium</option>
        <option value="hard">Hard</option>
      </select>

      {error && (
        <p role="alert" className="mt-3 text-sm text-critical">
          {error}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <button type="submit" className={buttonStyles()} disabled={saving}>
          {saving ? 'Saving…' : 'Save, ready to send'}
        </button>
        <button type="button" className={buttonStyles({ intent: 'quiet' })} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
