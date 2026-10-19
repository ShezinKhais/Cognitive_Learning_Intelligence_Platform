import { motion } from 'motion/react'

import { Panel, Tag, type Tone } from '../../components/ui/primitives'
import {
  engagementCounts,
  engagementStatusLabel,
  evidenceCoverageLabel,
  shortStudentId,
} from './lecturerAttention'

import type {
  EngagementStatus,
  LecturerEngagement,
} from './lecturerAttention'

interface LecturerAttentionPanelProps {
  students: LecturerEngagement[]
  loading: boolean
  error: string | null
  sessionStatus: string | undefined
}

const TONE: Record<EngagementStatus, Tone> = {
  engaged: 'good',
  at_risk: 'mixed',
  disengaged: 'poor',
  insufficient_data: 'neutral',
}

function computedAt(value: string): string {
  return Number.isNaN(Date.parse(value))
    ? 'time unknown'
    : new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Engagement estimates for the class. They are estimates from the signals
 * students have chosen to share, not proof of attention, and are kept apart
 * from how anyone is answering. A missing camera or microphone counts as
 * no evidence, never as zero.
 */
export default function LecturerAttentionPanel({
  students,
  loading,
  error,
  sessionStatus,
}: LecturerAttentionPanelProps) {
  const counts = engagementCounts(students)
  const isActive = sessionStatus === 'active'

  const bands = [
    { key: 'engaged', label: 'Engaged', count: counts.engaged, colour: 'bg-success' },
    { key: 'at_risk', label: 'At risk', count: counts.atRisk, colour: 'bg-warning' },
    { key: 'disengaged', label: 'Needs attention', count: counts.needsAttention, colour: 'bg-critical' },
    { key: 'insufficient', label: 'Not enough data', count: counts.insufficientData, colour: 'bg-muted-foreground/40' },
  ]

  return (
    <Panel
      className="lg:col-span-2"
      title="Engagement"
      description="Estimates from the signals students share. Not proof of attention, and separate from how they answer."
      actions={
        loading ? (
          <span role="status" className="text-sm text-muted-foreground">
            Updating…
          </span>
        ) : undefined
      }
    >
      {error && (
        <p role="alert" className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          {students.length > 0 ? `${error} Showing the last figures that loaded.` : error}
        </p>
      )}

      {!isActive ? (
        <p className="text-sm text-muted-foreground">Engagement shows while the class is running.</p>
      ) : students.length === 0 && !loading && !error ? (
        <p className="text-sm text-muted-foreground">
          Nothing yet. Figures appear once there is enough activity; a student sharing no camera or microphone is
          not counted against.
        </p>
      ) : null}

      {students.length > 0 && (
        <>
          <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
            {bands.map((band) =>
              band.count > 0 ? (
                <motion.div
                  key={band.key}
                  className={`${band.colour} h-full border-r-2 border-card last:border-r-0`}
                  initial={false}
                  animate={{ width: `${(band.count / counts.total) * 100}%` }}
                  transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                />
              ) : null,
            )}
          </div>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {bands.map((band) => (
              <div key={band.key} className="flex items-center gap-2">
                <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${band.colour}`} />
                <dt className="text-muted-foreground">{band.label}</dt>
                <dd className="font-semibold tabular-nums">{band.count}</dd>
              </div>
            ))}
            <div className="flex items-center gap-2 sm:ml-auto">
              <dt className="text-muted-foreground">Students</dt>
              <dd className="font-semibold tabular-nums">{counts.total}</dd>
            </div>
          </dl>

          <ul className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {students.map((student) => (
              <li
                key={student.student_id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="font-mono text-sm" title={student.student_id}>
                    {shortStudentId(student.student_id)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {evidenceCoverageLabel(student.confidence)}, at {computedAt(student.computed_at)}
                  </p>
                </div>
                <Tag tone={TONE[student.status]}>{engagementStatusLabel(student.status)}</Tag>
              </li>
            ))}
          </ul>

          <p className="mt-4 text-xs text-muted-foreground">
            Students are shown by a shortened ID, and the signals behind each estimate are not shown.
          </p>
        </>
      )}
    </Panel>
  )
}
