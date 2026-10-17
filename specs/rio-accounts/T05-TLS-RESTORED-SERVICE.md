# T05 — Restored TLS application state and real OIDC proof

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

This continuation is stacked on draft #71 at frozen green head
`a1394447403b4be7b5ce5de938dbdb4b25f8b9b1`. Its exact-head GO-13 and full RIO
passed. Historical failures remain evidence; causes #51/#60/#64 remain UNKNOWN.

## Explicit library construction

`AppState::discover_tls_synthetic_restore` accepts only the existing separate
`SyntheticTlsRestoreDbConfig`. Mode and client-secret validation precede any
connection or recovery mutation. The storage constructor validates the existing
fixed clone and commits its atomic recovery fence before discovery or returned
application state. A subsequent discovery failure returns no state but does not
undo the fence. Each explicit invocation fences again.

The provider, client, callback and browser endpoints remain fixed loopback values.
There is no normal executable flag, environment selector, new profile, arbitrary
database choice or staging activation. The existing primary constructor retains
its behavior. Certificate/hostname verification, explicit CA, required SCRAM
channel binding, binding policy, cookie policy and session lifetimes are unchanged.

## First fence: actual copied cookies through the service

The native archive preparation and verification remain the fifth and sixth exact
TLS cases. The two still-live sessions now store hashes of fixed syntactically
valid fixture cookies; a third cookie is the revoked control. Before construction,
the native restored clone must match all ten source tables and both copied
sessions must still be valid against the database clock, epoch, account status
and rotation flags. Expiry cannot satisfy this proof.

The empty clone, invalid credentials and missing binding refuse application-state
construction without bootstrap, repair or recovery mutation. The sixth case's
first actual recovery uses the new AppState constructor. Immediately after return,
raw session and login-transaction counts must be zero, before any request can
purge them. Then `/api/me` and `/api/consent` with each of the three old cookies
must return 401 without Set-Cookie. Existing consent, epoch, recovery-generation,
fresh bound issuance and unchanged primary-snapshot assertions remain required.
These are fixture-issued cookies through the real router, independent of the
following browser proof.

## Second fence: fresh real browser login on the clone

`tls_oidc_tests::postgres_tls_restore_oidc_contract` is a seventh separate ignored
case. It explicitly fences the same clone again, starts the existing test-only
HTTPS listener and runs the unchanged five OIDC browser cases against real
loopback Keycloak. Actual authorization-code/PKCE callbacks issue new bound
cookies through TLS-backed restored storage. In-memory sessions remain empty.
The complete primary table snapshot before and after must match; the opaque
test-only comparison never prints rows. Listener shutdown and port rebind are
required even when the browser fails.

The private harness selects only two fixed targets internally: primary or restore.
The restore config and `restore-oidc-summary.json` are fixed paths. The reporter
accepts only its default target or `{target: 'restore'}`, plus the three ignored
data fields injected by pinned Playwright (`configDir`, `_mode`, `_commandHash`).
Metadata accessors and unknown options fail; no arbitrary summary filename or
environment override exists. Both precreated summaries retain private
owner, regular-file, single-link, empty-file and descriptor-identity checks.
Each summary requires the same five unique successful fixed case IDs and zero
suite errors. Raw browser errors, cookies, URLs and secret values stay private.

The fixture's V2 aggregate requires seven exact selected successes in separate
private logs, all four native backup/restore phases and verified owned cleanup.
Stale restore summaries/logs, wrong or zero selected cases and a failed seventh
case cannot reuse earlier successes. Existing retries and timeouts are unchanged.
The original development OIDC, mobile, durability and independent native restore
proofs still run. Local compilation or platform-skipped tests establish no Linux
TLS/browser PASS; the complete exact-head workflows must finish.

This proves a closed synthetic restored-service boundary. Off-site retention,
archive encryption/key policy, production activation and human acceptance remain
separate. Human acceptance #50, causes #51/#60/#64, physical Android/manual screen
reader, real accounts/identities/invitations, NOVA contact, staging and production
remain HOLD.
