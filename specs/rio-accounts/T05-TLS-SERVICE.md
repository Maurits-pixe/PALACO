# T05 — Explicit TLS storage in the closed service kernel

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO LAUNCHER OR DEPLOYMENT CHANGE.

This slice is stacked on draft #66 at frozen head `b557c89cd200c99b5574bb63597162d3c1fded34`. The existing TLS store previously had no service constructor. `AppState::discover_tls_synthetic(mode, client_secret, database)` now validates the same explicit synthetic-mode/secret policy as DevConfig, connects through `PgStore::connect_tls_synthetic`, and discovers the fixed loopback identity provider. Storage failures produce a fixed error and do not fall back to the local plaintext store.

Both storage paths share one private discovery implementation. It constructs `RuntimeEndpoints::loopback()` internally; callers cannot supply a staging plan, host, issuer or browser-origin override. The TLS path accepts the immutable `SyntheticTlsDbConfig`, whose role/database/TLS/CA/channel-binding policy remains fixed. It does not take a DevConfig whose local database URL could accidentally be ignored. No secret/config Debug representation is added.

The new constructor is a typed library API. The executable still selects the original 127.0.0.1:8088 development service and local database route; `DevConfig::from_env`, offline endpoint checker and recovery-fence command remain unchanged. There is no TLS environment selector, staging launcher, remote provider, proxy trust, account activation, new migration or dependency/lockfile change. TLS database recovery-fence/backup is not added by this slice; the existing native restore proof remains on its original isolated development database.

## Actual test boundary

The owned Linux fixture now executes two exact ignored Rust cases sequentially, each requiring exactly one selected test and a successful exit. Private logs are separate and must initially be empty. An old storage PASS or zero selected service cases cannot establish service success. `RIO_TLS_FIXTURE_EVIDENCE_V2` contains both fixed test names/results and an aggregate status, with cleanup required. The old `rustTest`/`rustTestPassed` fields identify only the first storage case.

1. The existing storage case proves the actual current connection uses TLS, wrong CA/name and plaintext are rejected, issuer/subject bindings fail closed and issued sessions can be revoked.
2. The new service case calls the real public constructor using the owned TLS database and the already-running standard synthetic Keycloak discovery endpoint. A format-valid test-only client secret is sufficient for public discovery; no token exchange is attempted. The case rejects invalid mode/secret, wrong CA/name and plaintext service storage, and requires a durable store with no memory sessions. The real router starts an S256 login with a TLS-backed one-use fence; an explicit provider-error callback consumes both in-memory and durable fences without granting a session.
3. Subsequent server-bound alpha/peer/beta sessions are deliberately seeded through the existing test binding API. The actual HTTP router enforces own-account reads, query-selector refusal, unchanged consent after wrong CSRF/origin, revision-bound grant/read and stale-revision conflict, actor-scoped logout-all, and persistent alpha/peer denial after constructing a new application state and TLS connection. Beta's cookie, CSRF and consent survive that reconstruction; its own logout then denies further access. All successful account/consent payloads retain HOLD/closed authority.

This proves real TLS-backed storage and the in-process HTTP boundary. It does **not** prove successful end-to-end OIDC login through this TLS service path, a browser TLS listener, persistent IdP operation, staging deployment or TLS-native backup/recovery. The existing full OIDC/browser/consent/revocation/backup suite still runs independently on the unchanged development profile.

## Verification and remaining gates

Local GNU Windows unit tests: 42 PASS; six external integration cases deliberately ignored until their owned fixtures run. The new TLS service test compiles and all-target Clippy passes. The 14 mocked TLS fixture tests require Linux ownership semantics; a Windows skip is not a PASS. Full exact-head Linux GO-13 and RIO, including both TLS cases and owned cleanup, are required before a candidate PASS claim.

Root causes #51/#60/#64 remain UNKNOWN; historical failed attempts are retained in parent drafts. Independent human review #50, physical Android/manual screen reader, real identities/accounts, invitations, NOVA contact, staging and production stay HOLD. No merge or deployment is authorized by test success.
