export interface SessionNotificationInput {
  sessionId: string
  courseCode: string
  title: string
  appBaseUrl: string
}

export function buildSessionNotificationCard(
  input: SessionNotificationInput,
): Record<string, unknown> {
  const target = new URL(
    `/teams/meeting?sessionId=${encodeURIComponent(input.sessionId)}`,
    input.appBaseUrl,
  ).toString()

  return {
    type: 'AdaptiveCard',
    version: '1.5',
    $schema: 'https://adaptivecards.io/schemas/adaptive-card.json',
    body: [
      {
        type: 'TextBlock',
        text: 'C.L.I.P live checkpoint',
        weight: 'Bolder',
        size: 'Medium',
      },
      {
        type: 'TextBlock',
        text: `${input.courseCode} — ${input.title}`,
        wrap: true,
      },
      {
        type: 'TextBlock',
        text: 'Open the student panel to respond to the current checkpoint.',
        wrap: true,
      },
    ],
    actions: [
      {
        type: 'Action.OpenUrl',
        title: 'Open C.L.I.P',
        url: target,
      },
    ],
  }
}
