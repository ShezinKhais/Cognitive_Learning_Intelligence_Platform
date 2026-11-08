import { app, authentication } from '@microsoft/teams-js'

import { apiUrl, setFallbackSignIn, type LoginResponse } from '../api'

// Teams single sign-on. Teams hands the tab an Entra token for C.L.I.P's API
// (webApplicationInfo in the manifest) and the backend checks it and returns
// the C.L.I.P account it belongs to: POST /auth/teams. No password is typed.

let refusal: string | null = null

/** Why Teams sign-in last failed in a way the person can act on, if it did. */
export function teamsSignInRefusal(): string | null {
  return refusal
}

export async function teamsSignIn(): Promise<LoginResponse | null> {
  let token: string
  try {
    // Teams resolves a repeated initialize with the first one.
    await app.initialize()
    token = await authentication.getAuthToken()
  } catch (caught) {
    // Kept so the sign-in page can say why, rather than only showing the form.
    const reason = caught instanceof Error ? caught.message : typeof caught === 'string' ? caught : ''
    refusal = `Teams could not give C.L.I.P your Microsoft sign-in${reason ? ` (${reason})` : ''}. Try again.`
    return null
  }
  const response = await fetch(apiUrl('/auth/teams'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (response.ok) {
    refusal = null
    return (await response.json()) as LoginResponse
  }
  if (response.status === 403) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    refusal = body?.error?.message ?? 'This Microsoft account has no C.L.I.P account yet.'
  }
  return null
}

/**
 * Use Teams sign-in whenever the refresh cookie is refused. Called before the
 * first render, so the first session check already has it; TeamsJS is only
 * initialised when a sign-in is needed.
 */
export function enableTeamsSignIn(): void {
  setFallbackSignIn(teamsSignIn)
}
