
import type { SessionStatus } from './types'
import type {
  AnswerReceipt,
  AttentionPrompt,
  CheckpointState,
  FeedbackResult,
  LiveConnectionStatus,
  LiveErrorEvent,
  LiveQuestion,
  QuestionClosedEvent,
  SessionStateEvent,
} from './liveSessionTypes'
import type { AiControls } from './liveSessionTypes'

// Every switch on, as the server has it until the lecturer turns one off.
const ALL_AI_ON: AiControls = {
  auto_checkpoints: true,
  learning_assistant: true,
  refocus_nudges: true,
  engagement_estimates: true,
}

export interface LiveSessionState {
  connection: LiveConnectionStatus
  sessionStatus: SessionStatus
  paused: boolean
  /** The lecturer's AI switches for the class. */
  ai: AiControls
  participantCount: number
  questionsDelivered: number
  /** Questions this student's answer was stored for, this session. */
  answeredIds: readonly string[]
  checkpoint: CheckpointState | null
  completedCheckpoint: CheckpointState | null
  attentionPrompt: AttentionPrompt | null
  error: LiveErrorEvent | null
  attentionConsentRejected: number
  /** The breakout room the lecturer assigned. null: never told. A label of
   * null: the rooms were closed, back to the main meeting. */
  assignedRoom: { label: string | null } | null
}

export type LiveSessionAction =
  | { type: 'connection'; status: LiveConnectionStatus }
  | { type: 'session-ended' }
  | { type: 'session-state'; payload: SessionStateEvent }
  | { type: 'question-delivered'; payload: LiveQuestion }
  | { type: 'select-option'; option: number }
  | { type: 'set-free-text'; value: string }
  | { type: 'answer-sent' }
  | {
      type: 'answer-confirmation-unknown'
      questionId: string
    }
  | { type: 'answer-receipt'; payload: AnswerReceipt }
  | { type: 'feedback-result'; payload: FeedbackResult }
  | { type: 'question-closed'; payload: QuestionClosedEvent }
  | { type: 'response-window-elapsed'; questionId: string }
  | { type: 'attention-prompt'; payload: AttentionPrompt }
  | { type: 'attention-prompt-cleared'; promptId: string }
  | { type: 'error'; payload: LiveErrorEvent }
  | { type: 'clear-error' }
  | { type: 'attention-consent-rejected' }
  | { type: 'room-assigned'; label: string | null }

export function initialLiveSessionState(
  status: SessionStatus,
  paused = false,
): LiveSessionState {
  return {
    connection: 'connecting',
    sessionStatus: status,
    paused,
    ai: ALL_AI_ON,
    participantCount: 0,
    questionsDelivered: 0,
    answeredIds: [],
    checkpoint: null,
    completedCheckpoint: null,
    attentionPrompt: null,
    error: null,
    attentionConsentRejected: 0,
    assignedRoom: null,
  }
}

function updateCheckpoint(
  state: LiveSessionState,
  update: (checkpoint: CheckpointState) => CheckpointState,
): LiveSessionState {
  if (!state.checkpoint) return state

  return {
    ...state,
    checkpoint: update(state.checkpoint),
  }
}

function questionStillOpen(
  state: LiveSessionState,
  checkpoint: CheckpointState,
): boolean {
  const closesAt = Date.parse(checkpoint.question.closes_at)

  return (
    state.sessionStatus === 'active' &&
    checkpoint.closed === null &&
    Number.isFinite(closesAt) &&
    closesAt > Date.now()
  )
}

function isFinished(state: LiveSessionState): boolean {
  return state.sessionStatus === 'ended' || state.sessionStatus === 'cancelled'
}

/** End the interaction, but keep uncertain submissions available for late receipts. */
function finishCheckpoint(state: LiveSessionState): CheckpointState | null {
  const checkpoint = state.checkpoint
  if (!checkpoint) return state.completedCheckpoint
  return {
    ...checkpoint,
    phase: checkpoint.phase === 'answering' ? 'missed'
      : checkpoint.phase === 'submitting' ? 'unconfirmed' : checkpoint.phase,
  }
}

function includeAnswer(state: LiveSessionState, questionId: string): readonly string[] {
  return state.answeredIds.includes(questionId)
    ? state.answeredIds : [...state.answeredIds, questionId]
}

export function liveSessionReducer(
  state: LiveSessionState,
  action: LiveSessionAction,
): LiveSessionState {
  switch (action.type) {
    case 'attention-consent-rejected':
      return { ...state, attentionConsentRejected: state.attentionConsentRejected + 1 }
    case 'room-assigned':
      // Told the rooms are closed before ever being given one: nothing to say.
      return action.label === null && state.assignedRoom === null
        ? state
        : { ...state, assignedRoom: { label: action.label } }
    case 'connection': {
      const connectionLost =
        action.status === 'offline' ||
        action.status === 'reconnecting' ||
        action.status === 'disconnected'

      const checkpoint = state.checkpoint

      let nextCheckpoint = checkpoint

      if (
        connectionLost &&
        checkpoint?.phase === 'submitting'
      ) {
        nextCheckpoint = {
          ...checkpoint,
          phase: 'unconfirmed',
        }
      } else if (
        action.status === 'connected' &&
        checkpoint?.phase === 'unconfirmed' &&
        questionStillOpen(state, checkpoint)
      ) {
        nextCheckpoint = {
          ...checkpoint,
          phase: 'answering',
        }
      }

      return {
        ...state,
        connection: action.status,
        checkpoint: nextCheckpoint,
      }
    }

    case 'session-ended': {
      return {
        ...state,
        connection: 'ended',
        sessionStatus: state.sessionStatus === 'cancelled' ? 'cancelled' : 'ended',
        paused: false,
        participantCount: 0,
        checkpoint: null,
        completedCheckpoint: finishCheckpoint(state),
        attentionPrompt: null,
      }
    }

    case 'session-state': {
      const sessionEnded =
        action.payload.status === 'ended' ||
        action.payload.status === 'cancelled'

      return {
        ...state,
        sessionStatus: action.payload.status,
        paused: sessionEnded ? false : action.payload.paused,
        ai: action.payload.ai,
        participantCount:
          sessionEnded ? 0 : action.payload.participant_count,
        questionsDelivered: action.payload.questions_delivered,
        checkpoint: sessionEnded ? null : state.checkpoint,
        completedCheckpoint: sessionEnded ? finishCheckpoint(state) : state.completedCheckpoint,
        attentionPrompt: sessionEnded ? null : state.attentionPrompt,
      }
    }

    case 'question-delivered': {
      if (isFinished(state)) return state
      if (
        state.completedCheckpoint?.question.question_id ===
        action.payload.question_id
      ) {
        return {
          ...state,
          completedCheckpoint: {
            ...state.completedCheckpoint,
            question: {
              ...state.completedCheckpoint.question,
              closes_at: action.payload.closes_at,
            },
          },
        }
      }

      if (
        state.checkpoint?.question.question_id ===
        action.payload.question_id
      ) {
        return {
          ...state,
          checkpoint: {
            ...state.checkpoint,
            question: {
              ...state.checkpoint.question,
              closes_at: action.payload.closes_at,
            },
          },
        }
      }

      return {
        ...state,
        checkpoint: {
          question: action.payload,
          phase: 'answering',
          selectedOption: null,
          freeText: '',
          receipt: null,
          feedback: null,
          closed: null,
        },
        completedCheckpoint: null,
        error: null,
      }
    }

    case 'select-option':
      return updateCheckpoint(
        state,
        (checkpoint) =>
          checkpoint.phase === 'answering' ||
          checkpoint.phase === 'rejected'
            ? {
                ...checkpoint,
                selectedOption: action.option,
                freeText: '',
                phase: 'answering',
              }
            : checkpoint,
      )

    case 'set-free-text':
      return updateCheckpoint(
        state,
        (checkpoint) =>
          checkpoint.phase === 'answering' ||
          checkpoint.phase === 'rejected'
            ? {
                ...checkpoint,
                freeText: action.value,
                selectedOption: null,
                phase: 'answering',
              }
            : checkpoint,
      )

    case 'answer-sent':
      return updateCheckpoint(state, (checkpoint) => ({
        ...checkpoint,
        phase: 'submitting',
        receipt: null,
      }))

    case 'answer-confirmation-unknown': {
      const checkpoint = state.checkpoint

      if (
        !checkpoint ||
        checkpoint.question.question_id !== action.questionId ||
        checkpoint.phase !== 'submitting'
      ) {
        return state
      }

      // If the connection has recovered and the question
      // is still open, allow the student to try again.
      const canRetry =
        state.connection === 'connected' &&
        questionStillOpen(state, checkpoint)

      return {
        ...state,
        checkpoint: {
          ...checkpoint,
          phase: canRetry ? 'answering' : 'unconfirmed',
        },
      }
    }

    case 'answer-receipt': {
      const finished = isFinished(state)
      const checkpoint = state.checkpoint ?? (finished ? state.completedCheckpoint : null)

      if (
        !checkpoint ||
        checkpoint.question.question_id !==
          action.payload.question_id
      ) {
        return state
      }

      // An older refused retry cannot undo feedback/confirmation already received.
      if (!state.checkpoint && checkpoint.phase === 'submitted') return state

      // A second submission may be rejected because the
      // server already saved the first submission.
      const alreadyAnswered =
        action.payload.reason ===
        'You have already answered this question.'

      const updated: CheckpointState = {
        ...checkpoint,
        phase:
          action.payload.accepted || alreadyAnswered
            ? 'submitted'
            : 'rejected',
        receipt: action.payload,
      }

      return action.payload.accepted || alreadyAnswered
        ? {
            ...state,
            checkpoint: null,
            completedCheckpoint: updated,
            answeredIds: includeAnswer(state, checkpoint.question.question_id),
          }
        : finished ? {
            ...state,
            checkpoint: null,
            completedCheckpoint: updated,
          }
        : {
            ...state,
            checkpoint: updated,
          }
    }

    case 'feedback-result': {
      const checkpoint = state.checkpoint

      if (
        checkpoint?.question.question_id ===
        action.payload.question_id
      ) {
        return {
          ...state,
          checkpoint: null,
          completedCheckpoint: {
            ...checkpoint,
            phase: 'submitted',
            feedback: action.payload,
          },
          answeredIds: includeAnswer(state, action.payload.question_id),
        }
      }

      const completed = state.completedCheckpoint

      return completed?.question.question_id ===
        action.payload.question_id
        ? {
            ...state,
            completedCheckpoint: {
              ...completed,
              phase: 'submitted',
              feedback: action.payload,
            },
            answeredIds: includeAnswer(state, action.payload.question_id),
          }
        : state
    }

    case 'question-closed': {
      const checkpoint = state.checkpoint

      if (
        !checkpoint ||
        checkpoint.question.question_id !==
          action.payload.question_id
      ) {
        return state
      }

      if (
        checkpoint.phase !== 'answering' &&
        checkpoint.phase !== 'rejected'
      ) {
        return {
          ...state,
          checkpoint: {
            ...checkpoint,
            closed: action.payload,
          },
        }
      }

      return {
        ...state,
        checkpoint: null,
        completedCheckpoint: {
          ...checkpoint,
          phase: 'missed',
          closed: action.payload,
        },
      }
    }

    case 'response-window-elapsed': {
      const checkpoint = state.checkpoint

      if (
        !checkpoint ||
        checkpoint.question.question_id !== action.questionId ||
        (
          checkpoint.phase !== 'answering' &&
          checkpoint.phase !== 'rejected'
        )
      ) {
        return state
      }

      return {
        ...state,
        checkpoint: null,
        completedCheckpoint: {
          ...checkpoint,
          phase: 'missed',
        },
      }
    }

    case 'attention-prompt':
      if (isFinished(state)) return state
      return {
        ...state,
        attentionPrompt: action.payload,
      }

    case 'attention-prompt-cleared':
      return state.attentionPrompt?.prompt_id ===
        action.promptId
        ? {
            ...state,
            attentionPrompt: null,
          }
        : state

    case 'error':
      return {
        ...state,
        error: action.payload,
      }

    case 'clear-error':
      return {
        ...state,
        error: null,
      }
  }
}

export function remainingResponseSeconds(
  closesAt: string,
  nowMilliseconds: number,
): number {
  const closeMilliseconds = Date.parse(closesAt)

  if (!Number.isFinite(closeMilliseconds)) {
    return 0
  }

  return Math.max(
    0,
    Math.ceil(
      (closeMilliseconds - nowMilliseconds) / 1000,
    ),
  )
}
