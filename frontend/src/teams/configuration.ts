export interface MeetingTabConfiguration {
  entityId: string
  contentUrl: string
  websiteUrl: string
  suggestedDisplayName: string
}

export function meetingTabConfiguration(
  origin: string,
): MeetingTabConfiguration {
  const contentUrl = new URL('/teams/meeting', origin).toString()

  return {
    entityId: 'clip.meeting',
    contentUrl,
    websiteUrl: contentUrl,
    suggestedDisplayName: 'C.L.I.P',
  }
}
