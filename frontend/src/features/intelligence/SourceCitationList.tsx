import {
  sourceCitationHeading,
  sourceExcerptText,
  type SourceCitation,
} from './citationFormat'

interface SourceCitationListProps {
  sources:
    | SourceCitation[]
    | null
    | undefined
}

export default function SourceCitationList({
  sources,
}: SourceCitationListProps) {
  if (
    sources === null ||
    sources === undefined ||
    sources.length === 0
  ) {
    return (
      <div>
        <h4 className="text-sm font-semibold">
          Sources
        </h4>

        <p className="mt-1 text-sm text-muted-foreground">
          Source citations unavailable
        </p>
      </div>
    )
  }

  return (
    <div>
      <h4 className="text-sm font-semibold">
        Sources
      </h4>

      <div className="mt-2 space-y-3">
        {sources.map((source) => {
          const excerpt =
            sourceExcerptText(
              source.excerpt,
            )

          return (
            <article
              key={source.id}
              className="rounded-md border border-border p-3"
            >
              <p className="text-sm font-medium">
                {sourceCitationHeading(
                  source,
                )}
              </p>

              {excerpt && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {excerpt}
                </p>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}