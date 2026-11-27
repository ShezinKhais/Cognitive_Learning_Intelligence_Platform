import { useState } from 'react'
import { InteractiveCheckpointAnswer } from '../student/InteractiveCheckpointAnswer'

import { authoredItems } from './interactiveAuthoring'

export function InteractiveQuestionFields({ kind, text, onChange }: {
  kind: 'matching' | 'ordering'
  text: string
  onChange: (value: string) => void
}) {
  const [preview, setPreview] = useState(false)
  const [draft, setDraft] = useState('')
  const items = authoredItems(kind, text)
  return (
    <div className="mt-3 space-y-2">
      <label className="block text-sm font-medium">
        {kind === 'matching' ? 'Correct pairs' : 'Items in the correct order'}
        <textarea rows={5} value={text} onChange={(event) => { setDraft(''); onChange(event.target.value) }}
          className="mt-1 block w-full rounded-md border border-input bg-background p-2" />
      </label>
      <p className="text-sm text-muted-foreground">
        {kind === 'matching' ? 'Enter 2–8 pairs, one per line, as Term | Meaning.' : 'Enter 2–8 items, one per line in solution order.'}
        {' '}Students receive shuffled choices.
      </p>
      <button type="button" className="text-sm font-semibold underline" aria-expanded={preview}
        disabled={!items} onClick={() => setPreview((open) => !open)}>{preview ? 'Hide preview' : 'Preview student view'}</button>
      {preview && items && <InteractiveCheckpointAnswer interaction={{ ...items, kind, choices: [...items.choices].reverse() }}
        draft={draft} disabled={false} onChange={setDraft} />}
    </div>
  )
}
