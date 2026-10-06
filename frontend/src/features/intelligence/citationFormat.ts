export interface SourceCitation {
  id: string
  material_title: string
  source_page: number | null
  source_slide: number | null
  excerpt: string | null
}

export function sourceCitationHeading(
  source: SourceCitation,
): string {
  const title =
    source.material_title.trim()

  const validSlide =
    typeof source.source_slide === 'number' &&
    Number.isFinite(source.source_slide) &&
    source.source_slide > 0

  const validPage =
    typeof source.source_page === 'number' &&
    Number.isFinite(source.source_page) &&
    source.source_page > 0

  if (title && validSlide) {
    return `${title} · Slide ${source.source_slide}`
  }

  if (title && validPage) {
    return `${title} · Page ${source.source_page}`
  }

  if (title) {
    return title
  }

  if (validSlide) {
    return `Slide ${source.source_slide}`
  }

  if (validPage) {
    return `Page ${source.source_page}`
  }

  return 'Source details unavailable'
}

export function sourceExcerptText(
  excerpt:
    | string
    | null
    | undefined,
): string | null {
  if (
    excerpt === null ||
    excerpt === undefined ||
    excerpt.trim().length === 0
  ) {
    return null
  }

  return excerpt.trim()
}