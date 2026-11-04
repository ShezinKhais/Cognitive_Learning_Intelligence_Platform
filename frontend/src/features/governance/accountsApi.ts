import { apiAuthenticatedGet, apiAuthenticatedRequest, type Role } from '../../api'

export interface Course {
  id: string
  code: string
  name: string
}

export interface Account {
  id: string
  name: string
  email: string
  role: Role
  active: boolean
  course: Course | null
  has_password: boolean
  teams_linked: boolean
}

export interface AccountIssued {
  account: Account
  /** Shown once. Only the hash is kept. */
  password: string | null
}

export interface AccountPage {
  items: Account[]
  total: number
  limit: number
  offset: number
}

export interface NewAccount {
  name: string
  email: string
  role: Role
  course_id: string | null
  website_password: boolean
}

export interface AccountChange {
  name?: string
  role?: Role
  active?: boolean
  course_id?: string
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export function listAccounts(filter: { role: Role | null; q: string; offset: number }): Promise<AccountPage> {
  const query = new URLSearchParams({ limit: '50', offset: String(filter.offset) })
  if (filter.role) query.set('role', filter.role)
  if (filter.q.trim()) query.set('q', filter.q.trim())
  return apiAuthenticatedGet(`/admin/accounts?${query}`)
}

export function createAccount(account: NewAccount): Promise<AccountIssued> {
  return apiAuthenticatedRequest('/admin/accounts', send('POST', account))
}

export function updateAccount(id: string, change: AccountChange): Promise<Account> {
  return apiAuthenticatedRequest(`/admin/accounts/${encodeURIComponent(id)}`, send('PATCH', change))
}

export function resetPassword(id: string): Promise<AccountIssued> {
  return apiAuthenticatedRequest(`/admin/accounts/${encodeURIComponent(id)}/password`, send('POST'))
}

export function listCourses(): Promise<Course[]> {
  return apiAuthenticatedGet('/admin/courses')
}

export function createCourse(course: { code: string; name: string }): Promise<Course> {
  return apiAuthenticatedRequest('/admin/courses', send('POST', course))
}
