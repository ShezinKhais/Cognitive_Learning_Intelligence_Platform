import { useEffect, useState } from 'react'

/**
 * Light or dark outside Teams, chosen per browser. Inside a meeting the
 * Teams theme decides (TeamsProvider), so nothing here runs there.
 */
export type ThemeChoice = 'system' | 'light' | 'dark'

export const THEME_CHOICES: ThemeChoice[] = ['system', 'light', 'dark']

const KEY = 'clip_theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === 'system' || value === 'light' || value === 'dark'
}

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): 'light' | 'dark' {
  return choice === 'system' ? (systemPrefersDark ? 'dark' : 'light') : choice
}

export function storedTheme(): ThemeChoice {
  try {
    const found = window.localStorage.getItem(KEY)
    return isThemeChoice(found) ? found : 'system'
  } catch {
    return 'system'
  }
}

function prefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK_QUERY).matches
}

let following = false
let stopFollowing: () => void = () => undefined

function paint(choice: ThemeChoice, root: HTMLElement = document.documentElement): void {
  const dark = resolveTheme(choice, prefersDark()) === 'dark'
  root.classList.toggle('dark', dark)
  root.style.colorScheme = dark ? 'dark' : 'light'
}

/**
 * Apply the stored choice and, for "system", keep following the device as it
 * changes. Called once Teams has said this is not a meeting.
 */
export function followStoredTheme(): void {
  following = true
  paint(storedTheme())
  stopFollowing()
  if (typeof window.matchMedia !== 'function') return
  const query = window.matchMedia(DARK_QUERY)
  const onChange = () => storedTheme() === 'system' && paint('system')
  query.addEventListener('change', onChange)
  stopFollowing = () => query.removeEventListener('change', onChange)
}

/** Teams has taken over the theme; stop following the device. */
export function stopFollowingTheme(): void {
  following = false
  stopFollowing()
  stopFollowing = () => undefined
  document.documentElement.style.colorScheme = ''
}

export function saveTheme(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(KEY, choice)
  } catch {
    // Private windows can refuse storage; the choice still holds for this page.
  }
  if (following) paint(choice)
}

export function useThemeChoice(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme)
  // Another tab changing it.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== KEY) return
      const next = isThemeChoice(event.newValue) ? event.newValue : 'system'
      setChoice(next)
      if (following) paint(next)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return [
    choice,
    (next) => {
      setChoice(next)
      saveTheme(next)
    },
  ]
}
