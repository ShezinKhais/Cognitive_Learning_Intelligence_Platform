/**
 * Local-only display state for a continuous camera-facing proxy.
 * Null observations are unavailable, not evidence of looking away.
 */
export function nextAwayStart(
  currentStart: number | null,
  forward: boolean | null,
  now: number,
): number | null {
  if (!Number.isFinite(now)) return null
  if (forward === true) return null
  if (forward === null) return null
  return currentStart === null ? now : currentStart
}

export function awayDurationSeconds(
  start: number | null,
  now: number,
): number | null {
  if (start === null || !Number.isFinite(now)) return null
  return Math.max(0, Math.floor((now - start) / 1000))
}
