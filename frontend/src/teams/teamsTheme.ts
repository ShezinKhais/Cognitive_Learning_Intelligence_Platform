import type { TeamsTheme } from './teamsTypes'

const THEME_CLASSES = ['dark', 'contrast', 'glass'] as const

export function applyTeamsTheme(
  theme: TeamsTheme,
  root: HTMLElement = document.documentElement,
): void {
  root.classList.remove(...THEME_CLASSES)

  // Teams' glass theme is light and translucent. The current design tokens
  // use the safe light-theme fallback until glass-specific tokens are added.
  if (theme !== 'default') {
    root.classList.add(theme)
  }

  root.dataset.teamsTheme = theme
}
