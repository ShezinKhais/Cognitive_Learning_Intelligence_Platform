import { useRef } from 'react'
import { answerIndices, type InteractiveCheckpoint } from './interactiveAnswer'

export function InteractiveCheckpointAnswer({ interaction, draft, disabled, onChange }: {
  interaction: InteractiveCheckpoint
  draft: string
  disabled: boolean
  onChange: (draft: string) => void
}) {
  const order = answerIndices(interaction, draft)
  const dragging = useRef<number | null>(null)
  const field = 'rounded-md border border-border bg-background px-2 py-1'
  function move(from: number, to: number) {
    if (disabled || from < 0 || from >= order.length || to < 0 || to >= order.length || from === to) return
    const next = [...order]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onChange(JSON.stringify(next))
  }

  return (
    <fieldset disabled={disabled} className="mt-6 min-w-0 space-y-3">
      <legend className="font-semibold">{interaction.kind === 'matching' ? 'Match the following' : 'Put the items in order'}</legend>
      {interaction.kind === 'matching' ? interaction.labels.map((label, row) => (
        <label key={label} className="grid gap-1 text-sm sm:grid-cols-2">
          <span className="break-words">{label}</span>
          <select className={field} value={order[row]} onChange={(event) => {
            const next = [...order]
            next[row] = Number(event.target.value)
            onChange(JSON.stringify(next))
          }}>
            <option value={-1}>Choose a match</option>
            {interaction.choices.map((choice, index) => (
              <option key={choice} value={index} disabled={order.some((selected, at) => at !== row && selected === index)}>
                {choice}
              </option>
            ))}
          </select>
        </label>
      )) : (
        <>
          <p className="text-sm text-muted-foreground">Drag items or use Move up and Move down.</p>
          <ol aria-label="Your current order" className="space-y-2">
            {order.map((index, position) => (
              <li key={index} className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2 text-sm"
                draggable={!disabled}
                onDragStart={(event) => {
                  dragging.current = position
                  event.dataTransfer.effectAllowed = 'move'
                  event.dataTransfer.setData('text/plain', '')
                }}
                onDragEnd={() => { dragging.current = null }}
                onDragOver={(event) => { if (!disabled && dragging.current !== null) event.preventDefault() }}
                onDrop={(event) => {
                  event.preventDefault()
                  const from = dragging.current
                  dragging.current = null
                  if (from !== null) move(from, position)
                }}
              >
                <span className="min-w-0 flex-1 break-words">{position + 1}. {interaction.choices[index]}</span>
                <button type="button" className={field} disabled={position === 0}
                  aria-label={`Move ${interaction.choices[index]} up`} onClick={() => move(position, position - 1)}>Move up</button>
                <button type="button" className={field} disabled={position === order.length - 1}
                  aria-label={`Move ${interaction.choices[index]} down`} onClick={() => move(position, position + 1)}>Move down</button>
              </li>
            ))}
          </ol>
        </>
      )}
    </fieldset>
  )
}
