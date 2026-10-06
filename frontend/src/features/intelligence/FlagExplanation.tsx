import { explanationText } from './intelligenceDisplay'

interface FlagExplanationProps {
  explanation:
    | string
    | null
    | undefined
}

export default function FlagExplanation({
  explanation,
}: FlagExplanationProps) {
  const unavailable =
    explanation === null ||
    explanation === undefined ||
    explanation.trim().length === 0

  return (
    <div>
      <h4 className="text-sm font-semibold">
        Why this was flagged
      </h4>

      <p
        className={
          unavailable
            ? 'mt-1 text-sm text-muted-foreground'
            : 'mt-1 text-sm'
        }
      >
        {explanationText(
          explanation,
        )}
      </p>
    </div>
  )
}