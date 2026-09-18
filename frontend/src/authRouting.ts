import type { CurrentUser, Role } from './api'

export function defaultPathForRole(role: Role): string {
  if (role === 'student') return '/student'
  if (role === 'admin') return '/admin'
  if (role === 'lecturer') return '/lecturer/materials'
  return '/access-denied'
}

export function intendedPathForRole(
  role: Role,
  requestedPath?: string,
): string {
  if (role === 'student' && requestedPath?.startsWith('/student')) {
    return requestedPath
  }

  if (role === 'admin' && requestedPath?.startsWith('/admin')) {
    return requestedPath
  }

  if (role === 'lecturer' && requestedPath?.startsWith('/lecturer')) {
    return requestedPath
  }

  return defaultPathForRole(role)
}

export function hasRequiredConsent(user: CurrentUser): boolean {
  return user.consents.includes('terms')
}
