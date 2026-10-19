import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

import DemoFrame from './DemoFrame'
import { SAMPLE_TERM } from './sampleData'

// Two measures on one scale (a share of the class), drawn as two lines and
// never combined into one figure: engagement is not comprehension.
const SERIES = [
  { key: 'engaged', label: 'Engaged', color: 'var(--series-1)', dash: undefined },
  { key: 'right', label: 'Answers right', color: 'var(--series-2)', dash: '6 4' },
] as const

const QUIET = [
  { name: 'Student A', weeks: 3, note: 'Answered every question, camera off' },
  { name: 'Student B', weeks: 2, note: 'Joined late in weeks 5 and 6' },
]

export default function EngagementDemo() {
  const [table, setTable] = useState(false)
  const last = SAMPLE_TERM[SAMPLE_TERM.length - 1]

  return (
    <DemoFrame>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-bold">CSIT321, this term</h3>
          <p className="text-sm text-muted-foreground">Share of the class in each session, for students who consented.</p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          {SERIES.map((series) => (
            <span key={series.key} className="inline-flex items-center gap-2">
              <svg width="22" height="8" aria-hidden>
                <line x1="1" y1="4" x2="21" y2="4" stroke={series.color} strokeWidth="2" strokeDasharray={series.dash} strokeLinecap="round" />
              </svg>
              {series.label}
            </span>
          ))}
          <button type="button" className="font-semibold text-primary link-sweep" onClick={() => setTable((value) => !value)} aria-pressed={table}>
            {table ? 'Show chart' : 'Show as table'}
          </button>
        </div>
      </div>

      {table ? (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 font-semibold">Week</th>
              <th className="py-2 font-semibold">Session</th>
              <th className="py-2 text-right font-semibold">Engaged</th>
              <th className="py-2 text-right font-semibold">Answers right</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_TERM.map((row) => (
              <tr key={row.week} className="border-b border-border last:border-0">
                <td className="py-2">{row.week}</td>
                <td className="py-2">{row.title}</td>
                <td className="py-2 text-right">{row.engaged}%</td>
                <td className="py-2 text-right">{row.right}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mt-4" role="img" aria-label={`Engagement and answers right across ${SAMPLE_TERM.length} weeks. Week ${last.week}: ${last.engaged}% engaged, ${last.right}% right.`}>
          <ResponsiveContainer width="100%" height={256}>
            <LineChart data={[...SAMPLE_TERM]} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="week" tickLine={false} axisLine={{ stroke: 'var(--border)' }} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} tickFormatter={(week) => `W${week}`} />
              <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip content={TermTooltip} cursor={{ stroke: 'var(--muted-foreground)', strokeDasharray: '3 3' }} />
              {SERIES.map((series) => (
                <Line
                  key={series.key}
                  dataKey={series.key}
                  name={series.label}
                  stroke={series.color}
                  strokeWidth={2}
                  strokeDasharray={series.dash}
                  dot={{ r: 4, fill: series.color, stroke: 'var(--card)', strokeWidth: 2 }}
                  activeDot={{ r: 6, stroke: 'var(--card)', strokeWidth: 2 }}
                  isAnimationActive
                  animationDuration={700}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <p className="mt-1 text-sm text-muted-foreground">
            Week {last.week}: <strong className="text-foreground">{last.engaged}%</strong> engaged,{' '}
            <strong className="text-foreground">{last.right}%</strong> of answers right.
          </p>
        </div>
      )}

      <div className="mt-6 border-t border-border pt-4">
        <h3 className="font-bold">Quiet for two sessions or more</h3>
        <p className="text-sm text-muted-foreground">Only you see this list. It is a reason to check in, not a mark against anyone.</p>
        <ul className="mt-3 space-y-2">
          {QUIET.map((student) => (
            <li key={student.name} className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border border-border px-4 py-2.5">
              <span className="font-semibold">{student.name}</span>
              <span className="text-sm text-muted-foreground">
                {student.weeks} sessions, {student.note.toLowerCase()}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </DemoFrame>
  )
}

function TermTooltip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload as (typeof SAMPLE_TERM)[number]
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-sm shadow-[var(--shadow-card-hover)]">
      <p className="font-semibold">
        Week {row.week}: {row.title}
      </p>
      <p className="text-muted-foreground">{row.engaged}% engaged</p>
      <p className="text-muted-foreground">{row.right}% of answers right</p>
    </div>
  )
}
