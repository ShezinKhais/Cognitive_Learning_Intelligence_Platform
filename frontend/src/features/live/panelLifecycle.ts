import type { LiveSessionStatus } from './useLiveSession'

// What the meeting panel shows as the session's status. Three sources can
// report it: the session as first loaded, the live socket, and the server's
// reply to the lecturer's own Start/Pause/Resume/End. The newest report wins,
// so a successful action shows at once even while the socket is down. The
// first load only fills in until something newer arrives.

export interface PanelLifecycle {
  status: LiveSessionStatus | null
  paused: boolean
  // True once the socket or an action has reported, so a slow first load
  // cannot put an older status back.
  reported: boolean
}

interface Snapshot {
  status: LiveSessionStatus
  paused: boolean
}

export type LifecycleEvent =
  | { type: 'loaded'; session: Snapshot }
  | { type: 'socket'; session: Snapshot }
  | { type: 'action'; session: Snapshot }

export const initialLifecycle: PanelLifecycle = { status: null, paused: false, reported: false }

export function lifecycleReducer(state: PanelLifecycle, event: LifecycleEvent): PanelLifecycle {
  if (event.type === 'loaded' && state.reported) return state
  return {
    status: event.session.status,
    paused: event.session.paused,
    reported: state.reported || event.type !== 'loaded',
  }
}
