import { confidenceLabel } from './intelligenceDisplay'

interface ConfidenceIndicatorProps {
  confidence:
    | number
    | null
    | undefined
}

export default function ConfidenceIndicator({
  confidence,
}: ConfidenceIndicatorProps) {
  const unavailable =
    confidence === null ||
    confidence === undefined ||
    !Number.isFinite(confidence) ||
    confidence < 0 ||
    confidence > 1

  return (
    <span
      className={
        unavailable
          ? 'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground'
          : 'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs font-medium'
      }
    >
      {confidenceLabel(
        confidence,
      )}
    </span>
  )
}