# T05 — Native TLS snapshot recovery fences old sessions before return

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

This continuation is stacked on draft #70 at frozen green head `b162fa054c20b5603aa396e4dcc8afce52e770c2`. Parent GO-13 and full RIO passed. Earlier negative runs and unknown causes #51/#60/#64 remain evidence; this recovery proof does not claim to fix them.

## Separate recovery target

`SyntheticTlsRestoreDbConfig` is a separate immutable type with the fixed role `rio_dev`, database `rio_synthetic_tls_restore` and public port 5432. It shares the existing strict DNS, DER CA, TLS, certificate/hostname and required SCRAM channel-binding policy. It has no public conversion to the ordinary primary config, arbitrary database selector, secret accessor or Debug representation. The test-only address is fixed to the owned loopback TLS server on 8091; ordinary primary configuration remains fixed to `rio_synthetic_tls`.

`PgStore::connect_tls_synthetic_restore` requires an existing valid synthetic namespace. An empty clone is refused without creating tables or accounts; missing bindings are refused without repairing them. Validation uses the existing bounded advisory/row-lock policy. The constructor then completes the existing atomic recovery fence before returning any usable store. Failure or cancellation returns no handle and closes its owned connection. Ordinary connections retain their previous initialization and session-preservation behavior.

The recovery transaction advances account epochs and recovery generation, deletes sessions and pending login transactions, clears consent grants/expiry and advances their revisions, and records the existing recovery audit event. Each explicit recovery invocation fences again. This is an explicit library storage operation; the normal executable and AppState launcher gain no restored-database selector or new profile.

## Actual native archive through verified TLS

The owned Linux TLS fixture first runs the four existing storage/bootstrap/router/real-OIDC cases. It then creates only the fixed empty recovery database with `createdb -T template0`; a preexisting target fails rather than being dropped or overwritten. Native clients use fixed localhost/loopback TCP addressing, CA/hostname verification, TLS minimum1.2, required channel binding, disabled GSS and bounded connection/command times. A bad-CA native-client refusal and a good current-TLS check precede the fresh-session preparation.

The preparation case verifies an empty existing target cannot bootstrap through the recovery constructor. It prepares two fresh primary sessions, a deliberately revoked third session, a pending login transaction and granted consent. Immediately afterward `pg_dump --schema=rio_synthetic --format=custom` copies schema and data; `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges` restores only into the fixed empty clone. Neither `--create` nor a destructive drop operation is used.

The archive remains in the owned container's private directory, with exclusive creation, regular-file/single-link/owner/mode checks, a bounded size and custom-format signature check before restoration. It never enters host logs or public evidence. Password values are read from the fixed private mounted credential file into the native client's environment; they never enter argument values or public diagnostics. The owned container/volume namespace is removed and checked at completion.

## Proof cannot rely on expiry

The verification case inspects the real clone through a separate TLS connection before constructing the recovered store. Both marker sessions must still be live against the database clock, account status/epoch and rotation flags; the revoked marker must be absent. Pending login and granted consent must be present. Existing idle/absolute lifetimes are unchanged. Expired or empty snapshots fail rather than count as recovery success.

A missing clone binding must refuse construction without advancing recovery or erasing snapshot state; the fixture restores that exact binding for the actual recovery proof. After constructor return, old markers are denied, session/login tables are empty, consent is cleared, and epochs/recovery generation/revisions have advanced. Raw primary snapshots must remain unchanged. A fresh bound storage session can then be issued on the clone. These are explicit fixture storage markers; the existing real browser OIDC proof remains separate.

Six exact Rust cases in distinct private logs, the native transport/create/archive/restore phases and owned cleanup are all required for aggregate V2 PASS. A first-case success, zero/mismatched selected case, failed native command, stale output or skipped recovery cannot satisfy the result. Local compilation and mocked checks do not establish actual TLS recovery PASS; exact-head GO-13 and the complete Linux RIO suite must finish. The original independent development-database native restore proof also remains required.

The proof uses synthetic data and an ephemeral private archive. External backup retention, at-rest encryption/key handling, off-site recovery, restored-service activation and production operations remain separate reviewed work. Human acceptance #50, unknown causes #51/#60/#64, physical Android/manual screen reader, real accounts/identities/invitations, NOVA contact, staging and production remain HOLD.
