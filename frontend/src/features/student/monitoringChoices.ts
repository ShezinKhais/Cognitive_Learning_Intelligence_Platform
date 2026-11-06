/** The student's optional monitoring choices on the consent page.
 *
 * Engagement monitoring is the main permission. The camera and microphone
 * indicators sit under it: the server ignores them without it, so they are
 * only ever saved as on when monitoring is on too. Saving a choice never
 * switches a device on; the student does that in a class. */

export type MonitoringChoices = {
  monitoring: boolean
  camera: boolean
  microphone: boolean
}

export function choicesToSave(choices: MonitoringChoices): MonitoringChoices {
  const { monitoring } = choices
  return {
    monitoring,
    camera: monitoring && choices.camera,
    microphone: monitoring && choices.microphone,
  }
}
