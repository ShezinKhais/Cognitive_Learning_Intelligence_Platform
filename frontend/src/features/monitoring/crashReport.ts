export type CrashKind = 'render' | 'script' | 'promise' | 'load'

const areas = new Set(['admin', 'consent', 'lecturer', 'login', 'student', 'teams'])

/** Keep route parameters and other arbitrary URL content out of telemetry. */
export function crashArea(pathname: string): string {
  const area = pathname.split('/')[1]
  return areas.has(area) ? `/${area}` : '/'
}
