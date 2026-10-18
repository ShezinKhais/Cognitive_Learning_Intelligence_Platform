/**
 * The intro plays once, straight after signing in: the sign-in page leaves a
 * note in sessionStorage and the shell takes it. A reload, a new tab, or a
 * page reached by link never replays it.
 */
const KEY = 'clip_intro'

export function requestIntro(): void {
  try {
    window.sessionStorage.setItem(KEY, '1')
  } catch {
    // Storage blocked: no intro, which is fine.
  }
}

// Decided once per page load: React may run a state initialiser twice, and
// the second run must not find the note already used up.
let decided: boolean | undefined

/** Whether to play the intro on this page load. */
export function takeIntro(): boolean {
  decided ??= readIntro()
  return decided
}

function readIntro(): boolean {
  try {
    const wanted = window.sessionStorage.getItem(KEY) === '1'
    window.sessionStorage.removeItem(KEY)
    if (!wanted) return false
    return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** The intro has played; nothing in this page load plays it again. */
export function introPlayed(): void {
  decided = false
}
