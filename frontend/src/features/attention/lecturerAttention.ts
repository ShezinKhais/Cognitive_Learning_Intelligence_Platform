export type EngagementStatus =
  | 'engaged'
  | 'at_risk'
  | 'disengaged'
  | 'insufficient_data'

export interface LecturerEngagement {
  student_id: string
  session_id: string
  score: number | null
  status: EngagementStatus
  confidence: number
  signals_available: string[]
  computed_at: string
}

export interface EngagementCounts {
  total: number
  engaged: number
  atRisk: number
  disengaged: number
  insufficientData: number
}

export function engagementStatusLabel(
  status: EngagementStatus,
): string {
  if (status === 'engaged') {
    return 'Engaged'
  }

  if (status === 'at_risk') {
    return 'At risk'
  }

  if (status === 'disengaged') {
    return 'Disengaged'
  }

  return 'Insufficient data'
}

export function engagementScoreLabel(
  score: number | null | undefined,
): string {
  if (
    score === null ||
    score === undefined ||
    !Number.isFinite(score) ||
    score < 0 ||
    score > 1
  ) {
    return 'Unavailable'
  }

  return `${Math.round(score * 100)}%`
}

export function engagementConfidenceLabel(
  confidence: number | null | undefined,
): string {
  if (
    confidence === null ||
    confidence === undefined ||
    !Number.isFinite(confidence) ||
    confidence < 0 ||
    confidence > 1
  ) {
    return 'Confidence unavailable'
  }

  return `${Math.round(
    confidence * 100,
  )}% confidence`
}

export function signalLabel(
  signal: string,
): string {
  if (signal === 'attempt_rate') {
    return 'Checkpoint participation'
  }

  if (signal === 'response_timing') {
    return 'Response timing'
  }

  if (signal === 'prompt_response') {
    return 'Attention check response'
  }

  if (signal === 'gaze') {
    return 'Camera-facing estimate'
  }

  if (signal === 'face_presence') {
    return 'Face presence'
  }

  if (signal === 'speaking') {
    return 'Voice activity'
  }

  return 'Other available signal'
}

export function engagementCounts(
  students: LecturerEngagement[],
): EngagementCounts {
  const counts: EngagementCounts = {
    total: students.length,
    engaged: 0,
    atRisk: 0,
    disengaged: 0,
    insufficientData: 0,
  }

  for (const student of students) {
    if (student.status === 'engaged') {
      counts.engaged += 1
    } else if (
      student.status === 'at_risk'
    ) {
      counts.atRisk += 1
    } else if (
      student.status ===
      'disengaged'
    ) {
      counts.disengaged += 1
    } else {
      counts.insufficientData += 1
    }
  }

  return counts
}

export function shortStudentId(
  studentId: string,
): string {
  const clean = studentId.trim()

  if (clean.length <= 8) {
    return clean || 'Unavailable'
  }

  return `${clean.slice(0, 8)}…`
}