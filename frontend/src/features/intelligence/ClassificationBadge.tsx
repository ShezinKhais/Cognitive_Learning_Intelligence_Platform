import {
  classificationLabel,
  type ComprehensionClassification,
} from './intelligenceDisplay'

interface ClassificationBadgeProps {
  classification:
    | ComprehensionClassification
    | null
    | undefined
}

export default function ClassificationBadge({
  classification,
}: ClassificationBadgeProps) {
  const unavailable =
    classification === null ||
    classification === undefined

  return (
    <span
      className={
        unavailable
          ? 'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground'
          : 'inline-flex rounded-full bg-muted px-2.5 py-1 text-xs font-medium'
      }
    >
      {classificationLabel(
        classification,
      )}
    </span>
  )
}