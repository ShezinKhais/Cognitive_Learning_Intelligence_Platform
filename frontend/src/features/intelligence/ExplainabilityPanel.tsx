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

  recommendation?:
    | string
    | null

  sources?:
    | SourceCitation[]
    | null
}

export default function ExplainabilityPanel({
  topic,
  classification,
  confidence,
  explanation,
  recommendation,
  sources,
}: ExplainabilityPanelProps) {
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

      {topic !== undefined && (
        <div className="mt-5">
          <p className="text-xs font-medium text-muted-foreground">
            Topic
          </p>

          <p className="mt-1 text-sm font-medium">
            {topic?.trim() || 'Topic unavailable'}
          </p>
        </div>
      )}

      {(classification !== undefined ||
        confidence !== undefined) && (
        <div className="mt-5 flex flex-wrap gap-3">
          {classification !== undefined && (
            <ClassificationBadge
              classification={classification}
            />
          )}

          {confidence !== undefined && (
            <ConfidenceIndicator
              confidence={confidence}
            />
          )}
        </div>
      )}

      {explanation !== undefined && (
        <div className="mt-5 border-t border-border pt-5">
          <FlagExplanation
            explanation={explanation}
          />
        </div>
      )}

      {recommendation !== undefined && (
        <div className="mt-5 border-t border-border pt-5">
          <RecommendationCard
            recommendation={recommendation}
          />
        </div>
      )}

      {sources !== undefined && (
        <div className="mt-5 border-t border-border pt-5">
          <SourceCitationList
            sources={sources}
          />
        </div>
      )}
    </section>
  )
}