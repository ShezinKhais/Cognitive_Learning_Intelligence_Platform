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