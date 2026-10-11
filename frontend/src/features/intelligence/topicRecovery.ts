export type TopicDifficultyLevel =
  | 'easy'
  | 'medium'
  | 'hard'

export interface TopicDifficulty {
  topic: string
  questions: number
  answers: number
  mastered: number
  partial: number
  struggling: number
  uncertain: number
  score: number | null
  level: TopicDifficultyLevel | null
  expected: TopicDifficultyLevel | null
}

export function difficultyLabel(
  level: TopicDifficultyLevel | null,
): string {
  if (level === 'easy') {
    return 'Easy'
  }

  if (level === 'medium') {
    return 'Medium'
  }

  if (level === 'hard') {
    return 'Hard'
  }

  return 'Not enough data'
}

export function difficultyScoreLabel(
  score: number | null,
): string {
  if (
    score === null ||
    !Number.isFinite(score) ||
    score < 0 ||
    score > 1
  ) {
    return 'Unavailable'
  }

  return score.toFixed(2)
}

export function recoveryMessage(
  topic: TopicDifficulty,
): string {
  if (topic.level === 'hard') {
    return 'Prioritise this topic for review.'
  }

  if (topic.level === 'medium') {
    return 'Consider a short clarification or follow-up activity.'
  }

  if (topic.level === 'easy') {
    return 'No immediate recovery action is indicated.'
  }

  return 'More responses are needed before judging topic difficulty.'
}