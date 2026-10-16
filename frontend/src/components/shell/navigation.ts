import type { Role } from '../../api'

/**
 * What each role can reach from the side menu. Built pages come first;
 * planned ones are listed under "Planned" so a reviewer can see the whole
 * product, and each says on its page what it will do and who builds it.
 */
export interface NavItem {
  to: string
  label: string
  planned?: boolean
  /** Paths that also mark this item as the current page. */
  matches?: readonly string[]
}

export const NAVIGATION: Record<Role, readonly NavItem[]> = {
  lecturer: [
    { to: '/lecturer/sessions', label: 'Sessions', matches: ['/lecturer/sessions'] },
    { to: '/lecturer/materials', label: 'Materials', matches: ['/lecturer/materials', '/materials/'] },
    { to: '/lecturer/groups', label: 'Breakout groups', planned: true },
    { to: '/lecturer/engagement', label: 'Engagement history', planned: true },
  ],
  student: [
    { to: '/student', label: 'My sessions', matches: ['/student/session/'] },
    { to: '/student/progress', label: 'Progress over time', planned: true },
  ],
  admin: [
    { to: '/admin', label: 'Imports' },
    { to: '/admin/status', label: 'System status' },
    { to: '/admin/governance', label: 'Data governance', planned: true },
  ],
}

export const ROLE_NAME: Record<Role, string> = {
  lecturer: 'Lecturer',
  student: 'Student',
  admin: 'Administrator',
}

/** The menu item for the current path: the longest match wins, so
 * /student/session/1 marks "My sessions" and not some shorter prefix. */
export function currentItem(role: Role, pathname: string): NavItem | undefined {
  let best: NavItem | undefined
  let bestLength = -1
  for (const item of NAVIGATION[role] ?? []) {
    for (const prefix of [item.to, ...(item.matches ?? [])]) {
      const hit = pathname === prefix || pathname.startsWith(prefix.endsWith('/') ? prefix : `${prefix}/`)
      if (hit && prefix.length > bestLength) {
        best = item
        bestLength = prefix.length
      }
    }
  }
  return best
}
