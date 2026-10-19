import { ApiError } from '../../api'
import type { IllustrationName } from './Illustration'

/** What went wrong, in words for a person, with the error kept for problemArt. */
export interface Problem {
  message: string
  cause: unknown
}

/** A server's own message when it gave one, otherwise `fallback`. */
export function problemOf(caught: unknown, fallback: string): Problem {
  return { message: caught instanceof ApiError ? caught.message : fallback, cause: caught }
}

/** The thing asked for is not there: removed, or a stale link. Trying again will not help. */
export function isNotFound(problem: Problem): boolean {
  return problem.cause instanceof ApiError && problem.cause.status === 404
}

/** The drawing that fits what went wrong: offline, gone, or the server's fault. */
export function problemArt(error: unknown): IllustrationName {
  if (typeof error === 'number') return problemArt(new ApiError(error, 'HTTP_ERROR', ''))
  if (error instanceof ApiError) {
    if (error.code === 'UNREACHABLE' || error.status === 0) return 'offline'
    if (error.status === 404) return 'not-found'
    if (error.status === 502 || error.status === 503 || error.status === 504) return 'server-down'
    if (error.status >= 500) return 'server-error'
  }
  if (error instanceof TypeError) return 'offline'
  return 'load-failed'
}
