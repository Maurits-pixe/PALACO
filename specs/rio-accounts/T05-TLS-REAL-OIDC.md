# T05 — Real browser OIDC backed by TLS storage

Status: TEST-ONLY ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

Stacked on draft #67 at frozen head `088b82f6cf2b3642c98f31bbc9e909e1d89c8c58`. Parent storage/service TLS proofs passed, but its full integration failed in a pre-consent Android callback with `network-changed`; that failure remains evidence under #51 and is not a demonstrated cause or fix for this slice.

## What the new proof does

`tls_oidc_tests::postgres_tls_oidc_contract` exists only under `cfg(test)` and is ignored until the owned Linux fixture explicitly selects it. It constructs the actual `AppState::discover_tls_synthetic` with the existing fixed TLS database configuration, then binds an HTTPS listener exclusively to 127.0.0.1:8088. A used port fails before startup. The normal application launcher has no new flag, environment selector or staging endpoint conversion.

The test reads only the fixed standard-fixture configuration/certificate/key files and the owned TLS-fixture password/CA/summary. Reads are bounded and require private same-owner directories, regular single-link files and stable file identity across open/read. Duplicate config keys, changed fixed certificate/key paths or invalid synthetic secrets are rejected with fixed errors. Neither credentials nor raw file contents are diagnostics.

The installed browser runner executes the existing five `accounts.spec.mjs` cases with zero retries and the existing per-test/session limits. A 120-second global browser bound and a 145-second parent bound limit the extra proof. It performs actual real-Keycloak code/S256 login, token exchange and signed-token verification, session-cookie issuance, own-account isolation and protected logout/expiry through the HTTPS service using real TLS PostgreSQL storage. No session is seeded and no fake provider or test endpoint is introduced. The loopback self-signed browser-certificate exception is inherited from the existing fixture; no public CA/browser trust claim is made.

The dedicated reporter emits only schema, five fixed test IDs/statuses and a bounded suite-error count. It requires exactly five unique passing cases, a successful overall browser result and zero suite errors. It writes only the existing empty 0600 `oidc-summary.json` under a descriptor-pinned owned `.tls-runtime` directory and validates its owner marker; missing files, unsafe modes, symlinks, hard links or old output fail closed. The Rust parent also checks the summary and child exit status. It shuts down the listener and requires exclusive rebinding of its port before success.

## Lifecycle and evidence

The owned TLS fixture runs storage, router and real-OIDC cases sequentially in distinct private logs. Aggregate V2 evidence requires all three exact names, selected-case results and verified container/private-file cleanup. A stale log or summary cannot satisfy a new run.

Cargo is spawned in its own process session. Linux `waitid` with `WNOWAIT` retains the direct child identity before process-group signaling; timeout/cancellation gives TERM grace, then bounded KILL/reap. Lost ownership fails closed before group signaling. The Node browser runner is also bounded and receives graceful termination before forced reaping. A process-group check alone is not a claim that every detached Chromium process was enumerated; normal Playwright closure, child status, listener closure and fixture-resource cleanup are the implemented checks.

Only the existing pinned Tokio process feature is enabled for development/test builds. Production dependency versions, lockfile, service code, identity rules, schema and launch configuration remain unchanged. The existing full development-profile OIDC, durable revocation, Android/desktop and isolated restore suite remain required after the three TLS proofs.

Local safety tests and compilation do not establish actual TLS/OIDC PASS. Exact-head GO-13 and full Linux RIO must finish, and first failures must be retained. Human acceptance #50, unknown causes #51/#60/#64, physical Android/manual screen reader, real identities/accounts, invitations, NOVA contact, staging and production remain HOLD. TLS-native backup/recovery remains separate future work.
