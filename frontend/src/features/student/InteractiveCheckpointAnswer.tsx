import { useLayoutEffect, useRef, useState } from 'react'
import { answerIndices, type InteractiveCheckpoint } from './interactiveAnswer'

export function InteractiveCheckpointAnswer({ interaction, draft, disabled, onChange }: {
  interaction: InteractiveCheckpoint
  draft: string
  disabled: boolean
  onChange: (draft: string) => void
}) {
  const order = answerIndices(interaction, draft)
  const dragging = useRef<number | null>(null)
  const list = useRef<HTMLOListElement>(null)
  const pendingFocus = useRef<{ index: number; direction: 'up' | 'down' } | null>(null)
  const [announcement, setAnnouncement] = useState('')
  useLayoutEffect(() => {
    const target = pendingFocus.current
    pendingFocus.current = null
    if (!target || disabled) return
    list.current?.querySelector<HTMLButtonElement>(
      `button[data-item="${target.index}"][data-move="${target.direction}"]`,
    )?.focus()
  }, [draft, disabled])

  const field = 'rounded-md border border-border bg-background px-2 py-1'
  function move(from: number, to: number, direction?: 'up' | 'down') {
    if (disabled || from < 0 || from >= order.length || to < 0 || to >= order.length || from === to) return
    const next = [...order]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    if (direction) {
      const focusDirection = to === 0 ? 'down' : to === order.length - 1 ? 'up' : direction
      pendingFocus.current = { index: item, direction: focusDirection }
    }
    setAnnouncement(`${interaction.choices[item]} moved to position ${to + 1} of ${order.length}.`)
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
          <p className="sr-only" role="status" aria-atomic="true">{announcement}</p>
          <ol ref={list} aria-label="Your current order" className="space-y-2">
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
                <button type="button" className={field} disabled={position === 0} data-item={index} data-move="up"
                  aria-label={`Move ${interaction.choices[index]} up`} onClick={() => move(position, position - 1, 'up')}>Move up</button>
                <button type="button" className={field} disabled={position === order.length - 1} data-item={index} data-move="down"
                  aria-label={`Move ${interaction.choices[index]} down`} onClick={() => move(position, position + 1, 'down')}>Move down</button>
              </li>
            ))}
          </ol>
        </>
      )}
    </fieldset>
  )
}
