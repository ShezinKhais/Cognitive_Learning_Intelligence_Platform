import type { InteractionInput, QuestionInteraction } from '../../api'

export function authoredItems(kind: string, text: string): InteractionInput | null {
  const rows = text.trim().split('\n').map((line) => line.trim()).filter(Boolean)
  if (rows.length < 2 || rows.length > 8) return null
  const cells = rows.map((row) => kind === 'matching' ? row.split('|').map((item) => item.trim()) : [row])
  if (cells.some((row) => row.length !== (kind === 'matching' ? 2 : 1) ||
    row.some((item) => !item || [...item].length > 180))) return null
  const choices = cells.map((row) => row[row.length - 1])
  const labels = kind === 'matching' ? cells.map((row) => row[0]) : []
  if ([choices, labels].some((items) => new Set(items.map((item) => item.toLowerCase())).size !== items.length)) return null
  return { labels, choices }
}

export function solutionLines(interaction: QuestionInteraction | undefined | null): string {
  if (!interaction) return ''
  return interaction.correct_order.map((index, row) => interaction.kind === 'matching'
    ? `${interaction.labels[row]} | ${interaction.choices[index]}`
    : interaction.choices[index]).join('\n')
}
