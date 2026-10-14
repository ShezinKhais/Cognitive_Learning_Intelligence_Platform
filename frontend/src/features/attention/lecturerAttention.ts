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
  needsAttention: number
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
    return 'Needs attention'
  }

  return 'Insufficient data'
}

export function evidenceCoverageLabel(
  confidence:
    | number
    | null
    | undefined,
): string {
  if (
    confidence === null ||
    confidence === undefined ||
    !Number.isFinite(
      confidence,
    ) ||
    confidence < 0 ||
    confidence > 1
  ) {
    return 'Coverage unavailable'
  }

  return `${Math.round(
    confidence * 100,
  )}% coverage`
}

export function engagementCounts(
  students: LecturerEngagement[],
): EngagementCounts {
  const counts: EngagementCounts = {
    total: students.length,
    engaged: 0,
    atRisk: 0,
    needsAttention: 0,
    insufficientData: 0,
  }

  for (const student of students) {
    if (
      student.status ===
      'engaged'
    ) {
      counts.engaged += 1
    } else if (
      student.status ===
      'at_risk'
    ) {
      counts.atRisk += 1
    } else if (
      student.status ===
      'disengaged'
    ) {
      counts.needsAttention += 1
    } else {
      counts.insufficientData += 1
    }
  }

  return counts
}

export function shortStudentId(
  studentId: string,
): string {
  const clean =
    studentId.trim()

  if (clean.length <= 8) {
    return (
      clean ||
      'Unavailable'
    )
  }

  return `${clean.slice(
    0,
    8,
  )}…`
}