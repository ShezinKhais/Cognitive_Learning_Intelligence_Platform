import {
  difficultyLabel,
  difficultyScoreLabel,
  recoveryMessage,
} from './topicRecovery'

import type {
  TopicDifficulty,
} from './topicRecovery'

interface TopicRecoveryPanelProps {
  topics: TopicDifficulty[]
}

export default function TopicRecoveryPanel({
  topics,
}: TopicRecoveryPanelProps) {
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Topic recovery
        </p>

        <h2 className="mt-1 text-lg font-semibold">
          Topics to revisit
        </h2>

        <p className="mt-1 text-sm text-muted-foreground">
          Topic difficulty is based on the stored comprehension
          classifications for student responses.
        </p>
      </div>

      {topics.length === 0 ? (
        <div className="mt-5 rounded-md border border-border p-4">
          <p className="text-sm text-muted-foreground">
            No topic recovery data is available yet.
          </p>
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          {topics.map((topic) => (
            <article
              key={topic.topic}
              className="rounded-md border border-border p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">
                    {topic.topic}
                  </p>

                  <p className="mt-1 text-sm text-muted-foreground">
                    {topic.answers}{' '}
                    {topic.answers === 1
                      ? 'answer'
                      : 'answers'}{' '}
                    across {topic.questions}{' '}
                    {topic.questions === 1
                      ? 'question'
                      : 'questions'}
                  </p>
                </div>

                <div className="rounded-full border border-border px-3 py-1 text-xs font-semibold">
                  {difficultyLabel(
                    topic.level,
                  )}
                </div>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                <div className="rounded-md bg-muted p-3">
                  <p className="text-xs text-muted-foreground">
                    Mastered
                  </p>

                  <p className="mt-1 text-lg font-semibold">
                    {topic.mastered}
                  </p>
                </div>

                <div className="rounded-md bg-muted p-3">
                  <p className="text-xs text-muted-foreground">
                    Partial
                  </p>

                  <p className="mt-1 text-lg font-semibold">
                    {topic.partial}
                  </p>
                </div>

                <div className="rounded-md bg-muted p-3">
                  <p className="text-xs text-muted-foreground">
                    Struggling
                  </p>

                  <p className="mt-1 text-lg font-semibold">
                    {topic.struggling}
                  </p>
                </div>

                <div className="rounded-md bg-muted p-3">
                  <p className="text-xs text-muted-foreground">
                    Uncertain
                  </p>

                  <p className="mt-1 text-lg font-semibold">
                    {topic.uncertain}
                  </p>
                </div>
              </div>

              <div className="mt-4 space-y-2 text-sm">
                <p>
                  <span className="font-medium">
                    Difficulty score:
                  </span>{' '}
                  {difficultyScoreLabel(
                    topic.score,
                  )}
                </p>

                <p>
                  <span className="font-medium">
                    Expected difficulty:
                  </span>{' '}
                  {difficultyLabel(
                    topic.expected,
                  )}
                </p>

                <p className="text-muted-foreground">
                  {recoveryMessage(
                    topic,
                  )}
                </p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}