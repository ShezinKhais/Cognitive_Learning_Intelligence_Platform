export type TeamsTheme = 'default' | 'dark' | 'contrast' | 'glass'

export interface TeamsContext {
  meetingId: string | null
  userId: string | null
  tenantId: string | null
  displayName: string | null
  loginHint: string | null
  locale: string
  theme: TeamsTheme
  frameContext: string
}

export type TeamsHostKind = 'teams' | 'simulated' | 'standalone'

export interface TeamsHost {
  readonly kind: TeamsHostKind
  initialize(): Promise<TeamsContext | null>
  onThemeChange(handler: (theme: TeamsTheme) => void): () => void
}
