import ClassificationBadge from './ClassificationBadge'
import ConfidenceIndicator from './ConfidenceIndicator'
import FlagExplanation from './FlagExplanation'
import RecommendationCard from './RecommendationCard'
import SourceCitationList from './SourceCitationList'

import type {
  ComprehensionClassification,
} from './intelligenceDisplay'

import type {
  SourceCitation,
} from './citationFormat'

interface ExplainabilityPanelProps {
  topic?: string | null

  classification?:
    | ComprehensionClassification
    | null

  confidence?:
    | number
    | null

  explanation?:
    | string
    | null

  sources?:
    | SourceCitation[]
    | null

  recommendation?:
    | string
    | null
}

export default function ExplainabilityPanel({
  topic,
  classification,
  confidence,
  explanation,
  sources,
  recommendation,
}: ExplainabilityPanelProps) {
  const topicLabel =
    topic?.trim() ||
    'Topic unavailable'

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          AI intelligence
        </p>

        <h3 className="mt-1 text-lg font-semibold">
          Flag details
        </h3>
      </div>

      <div className="mt-5">
        <p className="text-xs font-medium text-muted-foreground">
          Topic
        </p>

        <p className="mt-1 text-sm font-medium">
          {topicLabel}
        </p>
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <ClassificationBadge
          classification={
            classification
          }
        />

        <ConfidenceIndicator
          confidence={confidence}
        />
      </div>

      <div className="mt-5 border-t border-border pt-5">
        <FlagExplanation
          explanation={
            explanation
          }
        />
      </div>

      <div className="mt-5 border-t border-border pt-5">
        <SourceCitationList
          sources={sources}
        />
      </div>

      <div className="mt-5 border-t border-border pt-5">
        <RecommendationCard
          recommendation={
            recommendation
          }
        />
      </div>
    </section>
  )
}