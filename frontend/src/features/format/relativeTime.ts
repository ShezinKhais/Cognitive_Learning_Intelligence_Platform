/** How long ago something happened, in the words a person would use:
 * "Just now", "5 min ago", "3 h ago", "Yesterday", then the date. Used where
 * recency matters more than the exact time; the exact time goes in a title
 * or a <time> element beside it. */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

const DATE = new Intl.DateTimeFormat('en-AE', {
  day: 'numeric',
  month: 'short',
  timeZone: 'Asia/Dubai',
})

const DAY_KEY = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: 'Asia/Dubai',
})

/** Calendar days between two moments, in the class's time zone. */
export function daysBetween(at: number, now: number): number {
  const day = (time: number) => Date.parse(`${DAY_KEY.format(time)}T00:00:00Z`)
  return Math.round((day(now) - day(at)) / DAY)
}

export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  if (!value) return ''
  const at = Date.parse(value)
  if (Number.isNaN(at)) return ''
  const ago = now - at
  // A clock a little ahead of the server still reads as now.
  if (ago < MINUTE) return 'Just now'
  if (ago < HOUR) return `${Math.floor(ago / MINUTE)} min ago`
  const days = daysBetween(at, now)
  if (days === 0) return `${Math.floor(ago / HOUR)} h ago`
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return DATE.format(at)
}

/** formatRelative after a verb: "Uploaded 5 min ago", "Ended yesterday",
 * "Ended 17 Oct". Only a leading word is lowered, never a month. */
export function sinceVerb(verb: string, value: string | null | undefined, now = Date.now()): string {
  const ago = formatRelative(value, now)
  if (!ago) return ''
  const phrase = /^[A-Z][a-z]/.test(ago) && !/^[A-Z][a-z]{2} /.test(ago) ? ago[0].toLowerCase() + ago.slice(1) : ago
  return `${verb} ${phrase}`
}

/** "12:05" for twelve minutes, "1:02:05" past the hour. */
export function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  const mm = String(m).padStart(h > 0 ? 2 : 1, '0')
  return `${h > 0 ? `${h}:` : ''}${mm}:${String(s).padStart(2, '0')}`
}

const CLOCK = new Intl.DateTimeFormat('en-AE', { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Dubai' })
const DAY_CLOCK = new Intl.DateTimeFormat('en-AE', {
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'Asia/Dubai',
})

/** The time of day, with the weekday when the day is not obvious from
 * where it is shown. */
export function formatClock(value: string, withDay = false): string {
  const at = Date.parse(value)
  return Number.isNaN(at) ? '' : (withDay ? DAY_CLOCK : CLOCK).format(at)
}
