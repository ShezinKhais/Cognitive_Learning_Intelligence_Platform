/**
 * Shared visibility policy for the student learning assistant.
 * Used by the normal live page and the Microsoft Teams meeting panel.
 *
 * The Teams checkpoint dialog intentionally shows only the checkpoint.
 * The backend remains authoritative for chat permissions.
 */
export function liveAssistantVisible(
  featureEnabled: boolean,
  lecturerEnabled: boolean,
  sessionStatus: string,
  dialog: boolean,
): boolean {
  return (
    featureEnabled &&
    lecturerEnabled &&
    !dialog &&
    sessionStatus !== 'ended' &&
    sessionStatus !== 'cancelled'
  )
}