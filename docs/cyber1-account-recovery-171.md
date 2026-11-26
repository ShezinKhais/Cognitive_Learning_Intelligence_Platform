# Cyber 1 account recovery: Issue #171

## Recovery model

C.L.I.P supports administrator-assisted recovery for institution-managed
accounts with local website passwords.

Public self-service account recovery and unrestricted public registration
are not part of this implementation.

Microsoft Teams users normally recover their Microsoft credentials
through their institution's established Microsoft Entra ID recovery
process.

## Account holder instructions

If a website password is lost:

1. Contact the institution's authorized C.L.I.P administrator through
   an established institutional support channel.
2. Request account recovery without sending an existing password.
3. Complete the institution's identity verification procedure.
4. Receive the replacement password through an approved private channel.
5. Sign in using the replacement password and change it promptly.

An administrator must not issue credentials solely because someone
knows an account email address.

## Administrator recovery procedure

1. Verify the requester's identity using the institution's approved
   process. This process requires institutional sign-off.
2. Confirm that the operator is authorized to administer the account.
3. Use the existing administrator-only account password-reset endpoint.
4. Deliver the issued replacement password through an approved secure
   handover channel. Do not place it in tickets, public chats or logs.
5. Tell the account holder that existing C.L.I.P sessions will be
   invalidated and a new sign-in is required.
6. Confirm successful access through the institution's approved
   acceptance process.

The administrative reset is subject to the existing role and terms
consent requirements and existing audit handling.

## Session security behavior

The User table has a nonnegative account token version, initially zero.

Access and refresh JWTs carry that account version. In production,
authentication and refresh compare the signed version against the
current version persisted for the account.

A successful administrator password reset increases the version.
A successful local password change also increases the version.
Provisioning an existing staff account with a replacement website
password increases the version.

After the version increases, previously issued C.L.I.P access and
refresh tokens fail the current-account check.

A new local password sign-in or a new verified Microsoft Teams
sign-in receives the current version.

The change invalidates C.L.I.P sessions, not the user's Microsoft
Entra sessions.

After a successful administrator password reset or self-service
password change, the backend also closes the affected user's
currently registered WebSocket connections, including live-session
and personal progress channels. Other users' connections are not
intentionally disconnected.

WebSocket disconnection is currently process-local: each backend
process maintains its own connection registry. A multi-process or
multi-host deployment requires coordinated revocation across
instances. This implementation does not claim cross-instance
WebSocket disconnection.

Account-version checks for access and refresh tokens are enforced
in production mode. Development mode retains its existing
development-account authentication behavior.

After changing their own password, users are explicitly signed out
of the frontend and must sign in again.

Normal sign-out behavior is unchanged: clearing a refresh cookie
is not a general server-side session revocation mechanism.

## Database deployment

Apply the Alembic revision a15c0d1e2f36 before deploying backend
code that reads or writes User.token_version.

The migration adds a non-null integer column with default zero.
It does not erase existing users or require a password reset.

Production deployment and rollback require an approved operational
procedure. Do not run migrations against a live institution database
as part of local testing.

## Verified local checks

- New migration applied on isolated PostgreSQL database
  clip_cyber1_test at 127.0.0.1:55432.
- Alembic reported a15c0d1e2f36 as the current revision.
- Authentication suite: 36 passed, no skips.
- Additional PostgreSQL password-reset integration test: passed.
- Full Windows backend run: 3747 passed, 3 failed, 7 skipped.
- The retrieval encoding failure passed on rerun with PYTHONUTF8=1.
- Two Unix permission tests failed on Windows mode reporting and
  remain pending Linux validation.
- Ruff on changed Python files: all checks passed.

## Remaining acceptance gates

- Institution to approve recovery authorization and identity
  verification procedure.
- Institution to approve a secure one-time password handover channel.
- Verify the administrator HTTP reset workflow and accessible user
  recovery guidance in the deployed application.
- Verify role enforcement, non-enumerating responses and auditing
  at the actual API boundary.
- Review the corresponding password-change acceptance evidence
  and record deployment/browser details in Issue #175.
- Confirm full Linux CI results before marking this issue complete.

This document records implementation and local test evidence.
It does not claim production deployment or institutional approval.
