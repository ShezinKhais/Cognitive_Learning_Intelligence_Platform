/** What a crash report says, and whether it is worth sending. Kept free of
 * browser and network code so it can be tested on its own. */

export type CrashKind = 'render' | 'script' | 'promise'

export const MAX_REPORTS_PER_PAGE = 5

export function crashMessage(error: unknown): string {
  const text =
    error instanceof Error ? `${error.name}: ${error.message}` : typeof error === 'string' ? error : 'Unknown error'
  // No query strings, tokens or emails in a report.
  return text
    .replace(/https?:\/\/\S+/g, '[url]')
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '[email]')
    .replace(/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[token]')
    .slice(0, 500)
}

/** Remembers what this page has already reported, so a loop sends one. */
export class CrashBudget {
  private seen = new Set<string>()

  allow(kind: CrashKind, message: string): boolean {
    const key = `${kind}:${message}`
    if (this.seen.has(key) || this.seen.size >= MAX_REPORTS_PER_PAGE) return false
    this.seen.add(key)
    return true
  }
}
