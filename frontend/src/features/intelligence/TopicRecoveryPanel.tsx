import { Panel, SkeletonRows, Tag, type Tone } from '../../components/ui/primitives'
import {
  difficultyLabel,
  difficultyScoreLabel,
  recoveryMessage,
} from './topicRecovery'

import type {
  TopicDifficulty,
  TopicDifficultyLevel,
} from './topicRecovery'

interface TopicRecoveryPanelProps {
  topics: TopicDifficulty[]
  loading?: boolean
  error?: string | null
}

const LEVEL_TONE: Record<TopicDifficultyLevel, Tone> = {
  easy: 'good',
  medium: 'mixed',
  hard: 'poor',
}

const BREAKDOWN = [
  { key: 'mastered', label: 'Mastered' },
  { key: 'partial', label: 'Partial' },
  { key: 'struggling', label: 'Struggling' },
  { key: 'uncertain', label: 'Uncertain' },
] as const

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

export default function TopicRecoveryPanel({
  topics,
  loading = false,
  error = null,
}: TopicRecoveryPanelProps) {
  return (
    <Panel
      title="Topics to revisit"
      description="Hardest first, from how each answer was marked."
    >
      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-critical/30 bg-critical/10 px-3 py-2 text-sm text-critical"
        >
          {error}
        </p>
      )}

      {loading && topics.length === 0 ? (
        <SkeletonRows label="Loading topics" rows={2} />
      ) : topics.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Topics appear here once answers have been marked.
        </p>
      ) : (
        <ul className="-my-1 divide-y divide-border">
          {topics.map((topic) => (
            <li key={topic.topic} className="py-4 first:pt-1 last:pb-1">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold">{topic.topic}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {plural(topic.answers, 'answer', 'answers')} across{' '}
                    {plural(topic.questions, 'question', 'questions')}
                  </p>
                </div>

                {topic.level && (
                  <Tag tone={LEVEL_TONE[topic.level]}>
                    {difficultyLabel(topic.level)}
                  </Tag>
                )}
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
                {BREAKDOWN.map(({ key, label }) => (
                  <div key={key}>
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-lg font-semibold tabular-nums">{topic[key]}</dd>
                  </div>
                ))}
              </dl>

              <p className="mt-3 text-sm">
                <span className="text-muted-foreground">Difficulty score</span>{' '}
                <span className="font-semibold">{difficultyScoreLabel(topic.score)}</span>
                <span className="text-muted-foreground">, expected</span>{' '}
                <span className="font-semibold">{difficultyLabel(topic.expected)}</span>
              </p>

              <p className="mt-1 text-sm text-muted-foreground">
                {recoveryMessage(topic)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
