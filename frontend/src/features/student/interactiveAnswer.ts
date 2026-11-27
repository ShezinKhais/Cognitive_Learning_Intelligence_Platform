export interface InteractiveCheckpoint {
  kind: 'matching' | 'ordering'
  labels: string[]
  choices: string[]
}

export function answerIndices(interaction: InteractiveCheckpoint, draft: string): number[] {
  const defaults = interaction.choices.map((_, index) => interaction.kind === 'matching' ? -1 : index)
  try {
    const result: unknown = JSON.parse(draft)
    return Array.isArray(result) && result.length === defaults.length &&
      result.every((index) => Number.isInteger(index) && index < defaults.length &&
        (index >= 0 || (index === -1 && interaction.kind === 'matching'))) &&
      (interaction.kind === 'matching' || new Set(result).size === result.length)
      ? result : defaults
  } catch {
    return defaults
  }
}

export function completeAnswer(interaction: InteractiveCheckpoint, draft: string): number[] | null {
  const order = answerIndices(interaction, draft)
  return order.every((index) => index >= 0) && new Set(order).size === order.length ? order : null
}
