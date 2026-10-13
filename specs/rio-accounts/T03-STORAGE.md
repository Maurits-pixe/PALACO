# T03 — Durable synthetic RIO records

Status: ENGINEERING CANDIDATE / SYNTHETIC_ONLY. ACCOUNT-1, integration and production remain HOLD.

The user approved this continuation after reporting a successful two-phone guest transport diagnostic on 13 October 2026. That observation concerns the separate Citadel test-code relay. It does not enroll personal accounts or provide a safety-service approval. This storage slice builds on T02 commit `92d87448bec6195ad59dd5e7ec4ff15d5015b56a` in the existing draft PR #49.

## Scope and fixed local boundary

The Rust BFF keeps its exact HTTPS browser origin and fixed local Keycloak realm. PostgreSQL is a separate synthetic fixture on IPv4 loopback port8090. Only the fixed primary database and an isolated restore-test database are accepted by the storage client. The browser service rejects the restore database. No Render database, paid resource, invitation, mail, real-person binding or production operator is provisioned.

The client uses the maintained [tokio-postgres0.7.18](https://docs.rs/tokio-postgres/0.7.18/tokio_postgres/) driver. The disposable database image is pinned to PostgreSQL18.6 and an immutable digest, verified from [the official image metadata](https://github.com/docker-library/repo-info/blob/master/repos/postgres/remote/18.6-bookworm.md). Plain PostgreSQL transport is a loopback-only development exception; external endpoints and fallback stores are rejected.

## Stored state and authority

Versioned SQL defines synthetic accounts, unique issuer/subject bindings, sessions, enrollment placeholders, provisional IDs, purpose-bound consent, fixed audit records and a non-dispatching outbox. Only TST-alpha and TST-beta are admitted. Enrollment stays inactive. These records issue no Government mandate, official identity, safety approval, account activation or NOVA contact permission.

Opaque session cookies and login transaction references are stored by SHA256 digest. Raw cookie values, Keycloak credentials, access/refresh/ID tokens and private signing keys are absent from the RIO database. CSRF values are private session metadata and never belong in evidence. Login nonce and PKCE material remain bounded in BFF memory; a restart closes unfinished login transactions.

Session issue, replacement, consent changes and revocation use database transactions and actor/tenant fences. Caller identity comes from the stored session and fixed issuer/subject binding, never a browser-provided actor. SQL operations carry explicit ownership predicates. Logout-all increments only the caller's actor epoch. An authorization flow started before that revocation cannot create a fresh session using its stale epoch.

A successful mutation response follows its committed database transaction. Database failure or uncertain completion gives a closed response; there is no memory-authentication fallback. Health reflects actual storage connectivity. Development limits remain idle30seconds, absolute60seconds and login300seconds; these are test settings, not accepted production policy.

## Restart and restore contract

A normal BFF restart preserves unexpired committed sessions, stable CSRF metadata and revocation state. Returning an old cookie does not recover a revoked session.

A restore is a different operation. PostgreSQL's [SQL dump and restoration](https://www.postgresql.org/docs/18/backup-dump.html) recovers a snapshot rather than later revocations. The isolated restore fixture therefore applies a durable recovery fence before any restored record is used: all restored session bearers and pending authorizations are invalidated, actor epochs advance and contact consent stays closed. Restored enrollment placeholders remain inactive. Fresh sign-in is required; ordinary restart does not trigger this fence.

The backup is a temporary owner-only runtime file. The fixed restore destination cannot overwrite an arbitrary database or production resource. No dump, private cookie, invitation, credential or SQL data payload is published as a test artifact.

## Required evidence

The final recorded candidate must pass formatting, locked compilation, linting, existing OIDC/router/signature checks and actual PostgreSQL integration tests. Evidence must include unique bindings, isolation, concurrent single-use authorization, actor-specific revocation, bounded expiry, a database outage that closes access, browser sessions retained across restart, revocation retained across a second restart and an executed native dump/restore with recovery fencing.

Browser reports contain only fixed test IDs, phase names, outcomes and numeric source references. Private cross-process cookie/CSRF state is owner-only under ignored .runtime and removed after the test. Local fixture containers, volume, generated credentials and backup are removed at completion.

No independent security/privacy/operations acceptance, real accounts, end-to-end encryption or production release follows from this engineering evidence. T04–T08 and the operational implementation decisions retain their separate gates.
