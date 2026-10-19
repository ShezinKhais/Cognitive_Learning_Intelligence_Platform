import type { SessionReadiness } from './sessionActions'

export interface ReadinessItem {
  done: boolean
  working?: boolean
  title: string
  detail: string
  link?: { to: string; label: string }
}

/** What has to be true before a class can start, as a checklist with the
 * next step beside whatever is not done yet. */
export function readinessItems(readiness: SessionReadiness): ReadinessItem[] {
  const ready = readiness.materials_total - readiness.materials_processing - readiness.materials_failed
  return [
    {
      done: ready > 0,
      working: readiness.materials_processing > 0 && ready === 0,
      title: 'Lecture material',
      detail:
        readiness.materials_total === 0
          ? 'Upload the slides for this class.'
          : readiness.materials_processing > 0
            ? `${readiness.materials_processing} still being read.`
            : `${ready} ready${readiness.materials_failed ? `, ${readiness.materials_failed} could not be read` : ''}.`,
      link: ready > 0 ? undefined : { to: '/lecturer/materials', label: 'Go to materials' },
    },
    {
      done: readiness.deliverable_questions > 0,
      title: 'Questions ready to send',
      detail:
        readiness.deliverable_questions > 0
          ? `${readiness.deliverable_questions} ready to send in class.`
          : // Not a blocker: a class may start with none and have one made ready while it runs.
            'None yet. You can start, and make questions ready during the class.',
      link: readiness.deliverable_questions > 0 ? undefined : { to: '/lecturer/materials', label: 'Review questions' },
    },
  ]
}
