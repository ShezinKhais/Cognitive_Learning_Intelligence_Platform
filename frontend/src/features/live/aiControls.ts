import type { AiControls } from '../student/liveSessionTypes'

export type { AiControls }

/** One of the lecturer's AI switches, as the panel shows it. */
export interface AiSwitch {
  key: keyof AiControls
  label: string
  detail: string
}

export const AI_SWITCHES: readonly AiSwitch[] = [
  {
    key: 'auto_checkpoints',
    label: 'Automatic checkpoints',
    detail: 'Checkpoint questions go out on their own timer. Off: only you send them.',
  },
  {
    key: 'learning_assistant',
    label: 'Learning assistant',
    detail: 'Students can ask the tutor about the class material.',
  },
  {
    key: 'refocus_nudges',
    label: 'Refocus nudges',
    detail: 'A private prompt to a student who seems to have drifted off.',
  },
  {
    key: 'engagement_estimates',
    label: 'Engagement estimates',
    detail: 'Camera and microphone indicators, and engagement scores for the class.',
  },
]

export interface AiControlsView extends AiControls {
  course_defaults: AiControls
}

export function allOff(): AiControls {
  return { auto_checkpoints: false, learning_assistant: false, refocus_nudges: false, engagement_estimates: false }
}

export function allOn(): AiControls {
  return { auto_checkpoints: true, learning_assistant: true, refocus_nudges: true, engagement_estimates: true }
}

export function anyOn(controls: AiControls): boolean {
  return AI_SWITCHES.some(({ key }) => controls[key])
}

/** Only the four switches, without the course defaults that come with them. */
export function switchesOf(view: AiControls): AiControls {
  return {
    auto_checkpoints: view.auto_checkpoints,
    learning_assistant: view.learning_assistant,
    refocus_nudges: view.refocus_nudges,
    engagement_estimates: view.engagement_estimates,
  }
}

/** Whether these are already what every new class of the course starts with. */
export function matchesCourse(view: AiControlsView): boolean {
  return AI_SWITCHES.every(({ key }) => view[key] === view.course_defaults[key])
}

export function aiControlsPath(sessionId: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}/ai-controls`
}
