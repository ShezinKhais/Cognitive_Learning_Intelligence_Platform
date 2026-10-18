export interface PlannedFeature {
  title: string
  summary: string
  /** What a user will be able to do. */
  will: readonly string[]
  /** What already works today, so nobody waits for what is there. */
  today: readonly string[]
  /** The working preview shown on its page. */
  demo: 'groups' | 'engagement'
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
    demo: 'engagement',
  },
}
