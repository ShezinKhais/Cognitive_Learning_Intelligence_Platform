import { meeting } from '@microsoft/teams-js'

import type { StageHost } from './stage'

/** The Teams SDK's stage sharing, as the StageHost the rest of the app uses. */
export const teamsStageHost: StageHost = {
  available: () =>
    new Promise((resolve) => {
      // Where the host or meeting cannot share, Teams answers with an error
      // (or the call throws), which is "not available".
      try {
        meeting.getAppContentStageSharingCapabilities((error, capabilities) => {
          resolve(!error && capabilities?.doesAppHaveSharePermission === true)
        })
      } catch {
        resolve(false)
      }
    }),
  share: (url) =>
    new Promise((resolve, reject) => {
      meeting.shareAppContentToStage((error, result) => {
        if (error) {
          reject(new Error(String(error.message ?? 'stage sharing failed')))
          return
        }
        resolve(result === true)
      }, url)
    }),
}
