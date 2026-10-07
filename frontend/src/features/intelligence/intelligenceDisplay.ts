export type ComprehensionClassification =
  | 'mastered'
  | 'partial'
  | 'struggling'

export type ExplanationSource =
  | 'ai'
  | 'fallback'

export function classificationLabel(
  classification:
    | ComprehensionClassification
    | null
    | undefined,
): string {
  if (classification === 'mastered') {
    return 'Mastered'
  }

  if (classification === 'partial') {
    return 'Partial'
  }

  if (classification === 'struggling') {
    return 'Struggling'
  }

  return 'Classification unavailable'
}

export function confidenceLabel(
  confidence:
    | number
    | null
    | undefined,
): string {
  if (
    confidence === null ||
    confidence === undefined ||
    !Number.isFinite(confidence) ||
    confidence < 0 ||
    confidence > 1
  ) {
    return 'Confidence unavailable'
  }

  return `${Math.round(
    confidence * 100,
  )}% confidence`
}

export function explanationText(
  explanation:
    | string
    | null
    | undefined,
): string {
  if (
    explanation === null ||
    explanation === undefined ||
    explanation.trim().length === 0
  ) {
    return 'Explanation unavailable'
  }

  return explanation.trim()
}

export function recommendationText(
  recommendation:
    | string
    | null
    | undefined,
): string {
  if (
    recommendation === null ||
    recommendation === undefined ||
    recommendation.trim().length === 0
  ) {
    return 'Recommendation unavailable'
  }

  return recommendation.trim()
}

export function explanationSourceLabel(
  source:
    | ExplanationSource
    | null
    | undefined,
): string {
  if (source === 'ai') {
    return 'AI explanation'
  }

  if (source === 'fallback') {
    return 'Safe fallback explanation'
  }

  return 'Explanation source unavailable'
}

export function usableConfidenceReasons(
  reasons:
    | string[]
    | null
    | undefined,
): string[] {
  if (!reasons) {
    return []
  }

  return reasons.filter(
    (reason) =>
      reason.trim().length > 0,
  )
}