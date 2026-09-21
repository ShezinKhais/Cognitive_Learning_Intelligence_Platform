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

export function liveSessionReducer(
  state: LiveSessionState,
  action: LiveSessionAction,
): LiveSessionState {
  switch (action.type) {
    case 'connection':
      return {
        ...state,
        connection: action.status,
      }

    case 'session-ended':
      return {
        ...state,
        connection: 'ended',
        sessionStatus: 'ended',
        paused: false,
        checkpoint:
          state.checkpoint?.phase === 'answering'
            ? { ...state.checkpoint, phase: 'missed' }
            : state.checkpoint,
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
        participantCount: action.payload.participant_count,
        questionsDelivered: action.payload.questions_delivered,
        checkpoint:
          sessionEnded && checkpoint?.phase === 'answering'
            ? { ...checkpoint, phase: 'missed' }
            : checkpoint,
      }
    }

    case 'question-delivered':
      if (state.checkpoint?.question.question_id === action.payload.question_id) {
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
        error: null,
      }

    case 'select-option':
      return updateCheckpoint(state, (checkpoint) =>
        checkpoint.phase === 'answering' || checkpoint.phase === 'rejected'
          ? {
              ...checkpoint,
              selectedOption: action.option,
              freeText: '',
              phase: 'answering',
            }
          : checkpoint,
      )

    case 'set-free-text':
      return updateCheckpoint(state, (checkpoint) =>
        checkpoint.phase === 'answering' || checkpoint.phase === 'rejected'
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

    case 'answer-receipt':
      return updateCheckpoint(state, (checkpoint) =>
        checkpoint.question.question_id === action.payload.question_id
          ? {
              ...checkpoint,
              phase: action.payload.accepted ? 'submitted' : 'rejected',
              receipt: action.payload,
            }
          : checkpoint,
      )

    case 'feedback-result':
      return updateCheckpoint(state, (checkpoint) =>
        checkpoint.question.question_id === action.payload.question_id
          ? {
              ...checkpoint,
              phase: 'submitted',
              feedback: action.payload,
            }
          : checkpoint,
      )

    case 'question-closed':
      return updateCheckpoint(state, (checkpoint) => {
        if (checkpoint.question.question_id !== action.payload.question_id) {
          return checkpoint
        }

        return {
          ...checkpoint,
          phase:
            checkpoint.phase === 'answering' || checkpoint.phase === 'rejected'
              ? 'missed'
              : checkpoint.phase,
          closed: action.payload,
        }
      })

    case 'response-window-elapsed':
      return updateCheckpoint(state, (checkpoint) =>
        checkpoint.question.question_id === action.questionId &&
        (checkpoint.phase === 'answering' || checkpoint.phase === 'rejected')
          ? { ...checkpoint, phase: 'missed' }
          : checkpoint,
      )

    case 'attention-prompt':
      return {
        ...state,
        attentionPrompt: action.payload,
      }

    case 'attention-prompt-cleared':
      return state.attentionPrompt?.prompt_id === action.promptId
        ? { ...state, attentionPrompt: null }
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
  if (!Number.isFinite(closeMilliseconds)) return 0

  return Math.max(0, Math.ceil((closeMilliseconds - nowMilliseconds) / 1000))
}
