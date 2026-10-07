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

  confidenceReasons?:
    | string[]
    | null

  explanation?:
    | string
    | null

  explanationSource?:
    | 'ai'
    | 'fallback'
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
  confidenceReasons,
  explanation,
  explanationSource,
  recommendation,
  sources,
}: ExplainabilityPanelProps) {
  const usableConfidenceReasons =
    confidenceReasons?.filter(
      (reason) =>
        reason.trim().length > 0,
    ) ?? []

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

      {confidenceReasons !== undefined && (
        <div className="mt-5">
          <p className="text-xs font-medium text-muted-foreground">
            Confidence reasons
          </p>

          {usableConfidenceReasons.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
              {usableConfidenceReasons.map(
                (reason) => (
                  <li key={reason}>
                    {reason}
                  </li>
                ),
              )}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              Confidence reasons unavailable
            </p>
          )}
        </div>
      )}

      {explanation !== undefined && (
        <div className="mt-5 border-t border-border pt-5">
          <FlagExplanation
            explanation={explanation}
          />

          {explanationSource !== undefined &&
            explanationSource !== null && (
              <p className="mt-2 text-xs text-muted-foreground">
                Source:{' '}
                {explanationSource === 'ai'
                  ? 'AI explanation'
                  : 'Safe fallback explanation'}
              </p>
            )}
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