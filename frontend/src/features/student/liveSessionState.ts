
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

export interface LiveSessionState {
  connection: LiveConnectionStatus
  sessionStatus: SessionStatus
  paused: boolean
  participantCount: number
  questionsDelivered: number
  checkpoint: CheckpointState | null
  completedCheckpoint: CheckpointState | null
  attentionPrompt: AttentionPrompt | null
  error: LiveErrorEvent | null
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

export function initialLiveSessionState(
  status: SessionStatus,
  paused = false,
): LiveSessionState {
  return {
    connection: 'connecting',
    sessionStatus: status,
    paused,
    participantCount: 0,
    questionsDelivered: 0,
    checkpoint: null,
    completedCheckpoint: null,
    attentionPrompt: null,
    error: null,
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

export function liveSessionReducer(
  state: LiveSessionState,
  action: LiveSessionAction,
): LiveSessionState {
  switch (action.type) {
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
      const checkpoint = state.checkpoint

      return {
        ...state,
        connection: 'ended',
        sessionStatus: 'ended',
        paused: false,
        participantCount: 0,
        checkpoint:
          checkpoint?.phase === 'answering'
            ? null
            : checkpoint,
        completedCheckpoint:
          checkpoint?.phase === 'answering'
            ? { ...checkpoint, phase: 'missed' }
            : state.completedCheckpoint,
      }
    }

    case 'session-state': {
      const sessionEnded =
        action.payload.status === 'ended' ||
        action.payload.status === 'cancelled'

      const checkpoint = state.checkpoint

      return {
        ...state,
        sessionStatus: action.payload.status,
        paused: action.payload.paused,
        participantCount:
          sessionEnded ? 0 : action.payload.participant_count,
        questionsDelivered: action.payload.questions_delivered,
        checkpoint:
          sessionEnded && checkpoint?.phase === 'answering'
            ? null
            : checkpoint,
        completedCheckpoint:
          sessionEnded && checkpoint?.phase === 'answering'
            ? { ...checkpoint, phase: 'missed' }
            : state.completedCheckpoint,
      }
    }

    case 'question-delivered': {
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
      const checkpoint = state.checkpoint

      if (
        !checkpoint ||
        checkpoint.question.question_id !==
          action.payload.question_id
      ) {
        return state
      }

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
        }
      }

      const completed = state.completedCheckpoint

      return completed?.question.question_id ===
        action.payload.question_id
        ? {
            ...state,
            completedCheckpoint: {
              ...completed,
              feedback: action.payload,
            },
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
