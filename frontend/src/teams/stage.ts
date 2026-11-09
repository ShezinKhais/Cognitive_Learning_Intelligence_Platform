/**
 * Sharing the class to the Teams meeting stage.
 *
 * The lecturer shares a link, not data. Teams opens that link in every
 * participant's own client, so each person reaches C.L.I.P as themselves and
 * sees only what their own role and enrolment allow. Nothing about a student
 * is carried in the link or shown to the others.
 */

export type StageShareResult = 'shared' | 'unavailable' | 'refused' | 'failed'

/** What Teams offers, kept apart from the Teams SDK so it can be tested. */
export interface StageHost {
  /** Whether this meeting lets the app share to the stage at all. */
  available(): Promise<boolean>
  /** Share the link to the stage. True when Teams accepted it. */
  share(url: string): Promise<boolean>
}

/**
 * The page every participant is shown on the stage: the same meeting page
 * the side panel opens, for the same session. Teams requires HTTPS.
 */
export function stageContentUrl(origin: string, sessionId: string): string | null {
  let base: URL
  try {
    base = new URL(origin)
  } catch {
    return null
  }
  if (base.protocol !== 'https:' || !sessionId) {
    return null
  }
  const url = new URL('/teams/meeting', base.origin)
  url.searchParams.set('sessionId', sessionId)
  return url.toString()
}

export async function shareSessionToStage(
  host: StageHost,
  origin: string,
  sessionId: string,
): Promise<StageShareResult> {
  const url = stageContentUrl(origin, sessionId)
  if (url === null) {
    return 'unavailable'
  }
  try {
    if (!(await host.available())) {
      return 'unavailable'
    }
    return (await host.share(url)) ? 'shared' : 'refused'
  } catch {
    return 'failed'
  }
}

export const STAGE_MESSAGES: Record<StageShareResult, string> = {
  shared: 'Shared to the meeting stage. Everyone sees the class there.',
  unavailable: 'This meeting cannot share C.L.I.P to the stage.',
  refused: 'Teams did not share C.L.I.P to the stage.',
  failed: 'Sharing to the stage failed. Try again.',
}
