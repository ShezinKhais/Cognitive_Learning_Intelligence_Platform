const TEAMS_FRAME_ANCESTORS = [
  "'self'",
  'https://teams.microsoft.com',
  'https://*.teams.microsoft.com',
  'https://*.cloud.microsoft',
] as const

export function teamsFrameAncestors(): readonly string[] {
  return TEAMS_FRAME_ANCESTORS
}

export function teamsContentSecurityPolicy(): string {
  return [
    `frame-ancestors ${TEAMS_FRAME_ANCESTORS.join(' ')}`,
    "object-src 'none'",
    "base-uri 'self'",
  ].join('; ')
}