export interface PlannedFeature {
  title: string
  summary: string
  /** What a user will be able to do. */
  will: readonly string[]
  /** What already works today, so nobody waits for what is there. */
  today: readonly string[]
  owner: string
  /** The working preview shown on its page. */
  demo: 'groups' | 'engagement' | 'progress' | 'governance' | 'consideration'
}

export const PLANNED: Record<string, PlannedFeature> = {
  groups: {
    title: 'Breakout groups',
    summary: 'Split a class into rooms and see at a glance which rooms have gone quiet.',
    will: [
      'Form groups from the class list, or let students pick a room when they join',
      'Watch each room: who is in it, when it last spoke, and how it answered',
      'Bring every room back with one action',
    ],
    today: [
      'Students can name the room they are in from the live session',
      'A room that falls silent raises an alert on your live session page',
    ],
    owner: 'General CS (rooms), with the room interface to follow',
    demo: 'groups',
  },
  engagement: {
    title: 'Engagement history',
    summary: 'How a class engaged across a term, not only during the class in front of you.',
    will: [
      'See engagement for each past session, beside how the class answered',
      'Spot a student who has been quiet for several weeks, privately',
    ],
    today: [
      'Engagement is shown live during a session, for students who consented',
      'It is not stored after the session yet, so there is no history to show',
    ],
    owner: 'BBIS (storing engagement), Cyber 1 (fairness rules)',
    demo: 'engagement',
  },
  progress: {
    title: 'Progress over time',
    summary: 'Your topics across every session, so you know what to revisit before an exam.',
    will: [
      'See which topics you have mastered and which keep coming back',
      'Open the slides a topic came from',
    ],
    today: ['Each finished session has its own summary under My sessions'],
    owner: 'AI 1 (summaries), Cyber 1 (what a summary may say)',
    demo: 'progress',
  },
  governance: {
    title: 'Data governance',
    summary: 'Keep what C.L.I.P stores within its retention period, and act on requests to delete it.',
    will: [
      'Preview what the retention purge would delete, and run it',
      'Approve or refuse a request to delete a student’s data',
      'Read the audit log of every change made for a user',
    ],
    today: [
      'Uploaded files past the retention period are deleted every day',
      'Every change made for a signed-in user is written to the audit log',
    ],
    owner: 'BBIS (retention and deletion requests), Cyber 2 (this console)',
    demo: 'governance',
  },
  consideration: {
    title: 'Special consideration',
    summary: 'Ask for C.L.I.P to treat you differently in class, without having to explain why to your lecturer.',
    will: [
      'Choose what you need: no camera, no eye-tracking, more time, or no check-in prompts',
      'Say for how long, with an optional supporting document',
      'An administrator approves it, and your lecturer only learns that you have one',
    ],
    today: [
      'An accommodated student is never prompted and never marked disengaged',
      'Their answer speed is counted as typical, so their score cannot give them away',
    ],
    owner: 'Cyber 1 (fairness rules), Cyber 2 (the request and review screens)',
    demo: 'consideration',
  },
}
