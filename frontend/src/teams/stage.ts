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
export function stageContentUrl(
  origin: string,
  sessionId: string,
  allowInsecure = false,
): string | null {
  let base: URL
  try {
    base = new URL(origin)
  } catch {
    return null
  }
  if ((base.protocol !== 'https:' && !allowInsecure) || !sessionId) {
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
  /** Only for the local simulation, which runs on plain HTTP. */
  allowInsecure = false,
): Promise<StageShareResult> {
  const url = stageContentUrl(origin, sessionId, allowInsecure)
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

/**
 * A stand-in for the stage when developing without Teams: "sharing" opens the
 * stage link in a new window, as a simulated meeting's stage frame. Open that
 * window as a student to see what the class sees. It is only built where the
 * simulated Teams host is allowed, which is never a production build.
 */
export function simulatedStageHost(
  open: (url: string) => void,
  meetingId: string | null,
): StageHost {
  return {
    available: async () => true,
    share: async (url) => {
      const stage = new URL(url)
      stage.searchParams.set('teamsMock', '1')
      stage.searchParams.set('frame', 'content')
      if (meetingId) {
        stage.searchParams.set('meetingId', meetingId)
      }
      open(stage.toString())
      return true
    },
  }
}
