import type { Material } from '../materials/types'
import { groupOf, type SessionGroup } from '../sessions/format.ts'
import type { SessionSummary } from '../sessions/sessionsApi'

/** Lower case with accents and extra spaces taken out, so "  Week 7 " finds
 * "week 7" and "Résumé" finds "resume". */
function normalise(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/\s+/g, ' ').trim()
}

/** Every word of the query appears somewhere in the fields, in any order. */
export function matches(query: string, ...fields: (string | null | undefined)[]): boolean {
  const words = normalise(query).split(' ').filter(Boolean)
  if (words.length === 0) return true
  const haystack = normalise(fields.filter(Boolean).join(' '))
  return words.every((word) => haystack.includes(word))
}

export type SessionFilter = 'all' | SessionGroup

export function filterSessions<T extends Pick<SessionSummary, 'status' | 'title' | 'course_code'>>(
  sessions: readonly T[],
  query: string,
  filter: SessionFilter,
): T[] {
  return sessions.filter(
    (session) =>
      (filter === 'all' || groupOf(session.status) === filter) &&
      matches(query, session.title, session.course_code),
  )
}

export type MaterialFilter = 'all' | 'ready' | 'processing' | 'failed'

export function materialState(material: Pick<Material, 'status'>): Exclude<MaterialFilter, 'all'> {
  if (material.status === 'completed') return 'ready'
  if (material.status === 'failed') return 'failed'
  return 'processing'
}

export function filterMaterials<T extends Pick<Material, 'status' | 'filename' | 'course_code'>>(
  materials: readonly T[],
  query: string,
  filter: MaterialFilter,
): T[] {
  return materials.filter(
    (material) =>
      (filter === 'all' || materialState(material) === filter) &&
      matches(query, material.filename, material.course_code),
  )
}

/** How many of each kind, for the counts on the filter tabs. */
export function countBy<T, K extends string>(items: readonly T[], keyOf: (item: T) => K): Record<K, number> {
  const counts = {} as Record<K, number>
  for (const item of items) {
    const key = keyOf(item)
    counts[key] = (counts[key] ?? 0) + 1
  }
  return counts
}
