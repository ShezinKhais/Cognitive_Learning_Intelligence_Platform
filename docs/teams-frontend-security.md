# Microsoft Teams Frontend Security

This document defines the deployment security requirements for the C.L.I.P
frontend when it is embedded as a Microsoft Teams tab.

## Authorization Boundary

Microsoft Teams context must not be treated as proof of identity or as an
authorization source.

C.L.I.P authentication, consent checks, and role-based access control remain
authoritative for Student, Lecturer, and Administrator access.

Teams meeting, tenant, user, and frame context may be used only as contextual
or routing information.

A Teams-provided user or meeting identifier must never grant access to a
lecturer, administrator, session, or student resource by itself.

## HTTPS

All production Microsoft Teams tab pages must be served over HTTPS.

Development-only local tooling or simulation must not weaken the production
deployment requirements.

## Frame Ancestors

Microsoft Teams renders tab applications inside an iframe. The production
frontend therefore requires an HTTP Content-Security-Policy response header
that explicitly permits supported Microsoft hosts to embed C.L.I.P.

The minimum C.L.I.P Teams deployment policy is:

```http
Content-Security-Policy: frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.cloud.microsoft;





```

The `frame-ancestors` directive must be delivered as an HTTP response header.
It must not be replaced by a client-side TypeScript check or an HTML
`<meta>` element.

The deployment must also avoid a conflicting `X-Frame-Options` header that
would prevent Microsoft Teams from embedding the application.

### Deployment TODO

The final production hosting configuration must apply the
`Content-Security-Policy` header above to the C.L.I.P frontend responses before
the Microsoft Teams application is released.

The hosting platform has not yet been finalized in this branch, so a
platform-specific configuration is intentionally not added here. The deployed
environment must verify the response header before the Teams integration is
considered production-ready.

## Teams Simulation

Microsoft Teams simulation is for local development and demonstration only.

`VITE_TEAMS_MOCK_ENABLED` must remain disabled by default and must not be
enabled in the production environment.

The frontend must reject simulated Teams context in production builds even if
a mock query parameter is supplied.

## Lecturer Teams Routing

Lecturer and administrator access remains protected by C.L.I.P authentication,
consent, and role-based access control before a Teams-aware staff page is
rendered.

Teams context may help identify the meeting or session to open, but it must
never grant lecturer or administrator privileges.

Any Teams meeting-to-session relationship must resolve only to a session that
the authenticated C.L.I.P user is authorized to access.

## Deployment Verification

Before production release:

1. Confirm the frontend is served over HTTPS.
2. Confirm the required `Content-Security-Policy` response header is present.
3. Confirm no conflicting `X-Frame-Options` header blocks Teams embedding.
4. Confirm Teams simulation is disabled in production.
5. Confirm C.L.I.P authentication, consent, and RBAC remain authoritative.
6. Confirm lecturer and student Teams routes cannot expose unauthorized sessions.
