const TEAMS_FRAME_ANCESTORS = [
  "'self'",
  'https://teams.microsoft.com',
  'https://*.teams.microsoft.com',
  'https://*.cloud.microsoft',
] as const

/**
 * Hosts permitted to embed the C.L.I.P Teams frontend.
 *
 * These values follow Microsoft's Teams tab requirements. The legacy Teams
 * hosts are retained alongside *.cloud.microsoft for compatibility during
 * Microsoft's host-domain migration.
 */
export function teamsFrameAncestors(): readonly string[] {
  return TEAMS_FRAME_ANCESTORS
}

/**
 * Returns the CSP that the production frontend host must send as an HTTP
 * response header for C.L.I.P Teams pages.
 *
 * This function defines the policy only. It does not enforce CSP in the
 * browser by itself. Enforcement must be configured on the production
 * frontend host once that deployment platform is selected.
 */
export function teamsContentSecurityPolicy(): string {
  return [
    `frame-ancestors ${TEAMS_FRAME_ANCESTORS.join(' ')}`,
    "object-src 'none'",
    "base-uri 'self'",
  ].join('; ')
}