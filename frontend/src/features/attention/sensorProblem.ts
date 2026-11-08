/** Why a camera or microphone could not start, in words the student can act
 * on. The browser's error name says which of several very different things
 * went wrong, and one message for all of them left nobody able to fix it. */

export function sensorProblem(label: string, error: unknown, inTeams: boolean): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : ''
  const message = error instanceof Error ? error.message : ''
  const device = label.toLowerCase()
  const allowIt = inTeams
    ? `In Teams, open the C.L.I.P app, choose ... then App permissions, and turn on Media. Then press Turn on again.`
    : `Allow the ${device} for this site from the icon at the left of the address bar, then press Turn on again.`
  switch (name) {
    case 'NotAllowedError':
      return `${label} permission was refused. ${allowIt}`
    case 'SecurityError':
      return `This window is not allowed to use the ${device}. ${allowIt}`
    case 'NotReadableError':
    case 'AbortError':
      return `The ${device} is in use by another app and could not be shared. Close the other app, or try again.`
    case 'NotFoundError':
    case 'OverconstrainedError':
      return `No ${device} was found on this device.`
  }
  if (message === 'Insecure') return `The ${device} needs a secure (https) page.`
  if (message.includes('processing')) {
    return `${label} started, but the on-device model could not load. Reload the page and try again.`
  }
  return `${label} unavailable. Check browser permission or device use in another app. You can continue without it.`
}
