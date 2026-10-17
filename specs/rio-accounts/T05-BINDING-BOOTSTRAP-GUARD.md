# T05 — Initialize once and validate synthetic bindings on reopen

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

This continuation is stacked on draft #68 at frozen head `0c82b9dcaa9ec71b938df4c0bec128d8c8dfc2d6`. Its three TLS proofs, including five real OIDC browser cases, passed. The full parent RIO run failed in Android `RIO-MOBILE-01` during a pre-consent callback with `network-changed`; that failure remains evidence under #51, cause UNKNOWN. This slice does not claim to fix that incident.

## Deliberate change to bootstrap semantics

Previously each connection reran migration `0001`, including its fixed synthetic seed. Missing binding lookup was already denied, but reopening could recreate a deleted row. The previous contract explicitly retained that seed behavior; it was not a demonstrated violation of the earlier lookup contract.

Both local development and explicit TLS connections now distinguish first initialization from an existing namespace. The existing advisory transaction lock covers namespace inspection, initialization or validation, and commit. Only absence of `rio_synthetic` permits running `0001`. A new database still receives exactly the two fictional accounts and their fixed loopback issuer/subjects. No schema version, dependency version, lockfile, account selector or staging provider is added.

An existing namespace never executes bootstrap DDL or seed DML. It must contain the ten expected permanent ordinary tables and the exact fixed guard/account/binding records. Missing objects/records, unexpected counts, types or values close construction with the existing value-free `Unavailable` category. No missing record or table is repaired. This is an existence and fixed-data check, not complete constraint/trigger integrity auditing or protection against an arbitrary privileged database operator.

Validation locks the durable guard first with `FOR UPDATE`, then the ordered accounts and bindings with `FOR SHARE` until commit. This follows normal business transaction lock order. It reads the guard directly rather than calling `locked()`, which advances time and purges expired records. Both permitted synthetic account statuses and existing nonnegative epochs/counters are accepted. Ordinary reopen preserves clock state, disabled status, epochs, recovery generation and existing business records. The original explicit development restore path still applies its recovery fence after successful validation.

## Real TLS regression and bounded evidence

The owned Linux fixture runs four exact ignored Rust cases in order: storage, bootstrap, HTTP service, then real OIDC browser. Each has a distinct private log; V2 aggregate evidence requires all four plus owned cleanup. The legacy first-storage fields retain their narrow meaning. Zero selected tests, a different test's success, old log contents or a failed bootstrap case cannot satisfy the aggregate.

`storage::bootstrap_tests::postgres_tls_bootstrap_contract` uses the independent fixed loopback TLS configuration and an abort-on-drop raw connection. Raw queries have five-second bounds and fixed error categories. It verifies exactly the two fixed issuer/subject bindings, then changes only owned fixture state to prove an intact reopen preserves disabled status, account version and all guard fields. A committed binding deletion must cause a new connection to refuse construction without recreating the row. An existing store must also deny replacement, leaving complete session, predecessor, audit and outbox snapshots unchanged. Separate missing-guard and temporarily renamed-table cases must remain unrepaired. Exact fixture restoration permits the subsequent service and browser proofs to run; no schema or data is dropped by these negative cases.

Fresh initialization is exercised first against the newly created owned TLS database. The unchanged development fixture, durable revocation/restarts, real OIDC, Android/desktop and native backup/restore suite remain required on the new head. Locally skipped Linux/external cases are not PASS. First CI failures must remain visible without blind retries or relaxed bounds.

Deleting a binding is not a new session revocation API. Already issued cookies retain the existing account epoch/status rules; no automatic deletion-based cookie invalidation is promised. Explicit actor revocation remains the supported path. A future migration or reviewed repair procedure must be designed separately rather than inferred from reopen.

Human acceptance #50, unknown causes #51/#60/#64, physical Android/manual screen reader, real accounts/identities/invitations, NOVA contact, staging and production remain HOLD. TLS-native backup/recovery remains separate work. No merge, deployment, provider resource or real-account authority is created.
