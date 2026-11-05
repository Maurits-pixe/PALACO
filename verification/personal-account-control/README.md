# Personal Account Control — executable reference model v0.14

Status: IMPLEMENTED / LOCAL MODEL TESTS PASS. Production and ACCOUNT-1: HOLD.
Base inspected: PALACO 1b2065af0dfe82e25b3f62c80d9f9873563f6afd.
Source: conversation Personal Account Control Contract v0.2; not canonized.

Run from repository root with Python 3 (standard library only):

```sh
python -m unittest discover -s verification/personal-account-control -v
```

This isolated verification slice does not change services/rio-accounts, login,
OIDC, the HTTP router, existing database migrations or deployment configuration.
It has no network listener and sends no invitations. All actor roles, recipient
bindings, checklist evidence and times are supplied by the synthetic fixture.
They do not establish identity, strong authentication or human authority.

Implemented: invitation hash/expiry/one-time use, explicit lifecycle transitions,
exact review checklist, scope revision invalidation, role separation, staging-only
activation, idempotency with payload conflict rejection, atomic SQLite activation
and audit, suspension/access recheck, expiry access denial and workspace isolation.
Recovery is a no-op demonstration: it cannot grant access. It is not an account
recovery implementation. SQL triggers prevent ordinary audit update/delete; a
SQLite file owner can bypass them. This is not a tamper-proof audit system.

## Evidence and remaining gaps

S01-S12 and append-only model checks: 137 slice tests plus 8 existing review-gate tests pass locally, plus one isolated dependency-free Rust boundary test. Full RIO service tests are blocked by missing dependencies/unreachable registry.
S02 tests wrong recipient/token, expiry and replay; explicit invitation revocation
is not implemented. S07 tests a completed suspension before activation. Additional two-connection
tests hold a write transaction while activation attempts BEGIN IMMEDIATE, then
commit suspension or mandate revocation and require the waiting activation to deny.
Two concurrent duplicate activations produce exactly one ACTIVE audit event. S09 tests model access checks, not browser
session/token invalidation. S10 tests recovery permission preservation only.
S12 tests wrong-workspace and expired access. No production SLA is inferred.

Not implemented/verified: invitation delivery, production mandate registry,
review evidence authentication, session
revocation adapters, REVOKED/EXPIRED lifecycle events, reactivation, denial-event
logging, dual-store-outage/restart guarantees,
other interleavings beyond the tested two-connection cases, HTTP/CSRF integration and UI. No clinical data is used.

## AI review using three lenses

TRIAS: reference model stays synthetic and cannot activate the existing service.
ORACLE: passing unit tests establish only the stated model scenarios; no runtime
integration, independent human review, CI result or canonical compliance claimed.
MENTOR: next slice should define authenticated evidence intake and the HTTP adapter
contract, then address audit-failure fallback for suspension before runtime wiring. No production
transition is authorized by this model or its tests.

## v0.2 evidence and mandate boundary

Fixture mandates are seeded explicitly with `seed_fixture_mandates()`. Without
that call, privileged operations deny. Mandates bind actor, role, workspace,
scope, expiry and revocation in shared SQLite storage. Activation rereads both
activator and reviewer mandates inside its write transaction. Review evidence
binds revision, reviewer, workspace, scope, policy version, expiry and synthetic
evidence reference. Policy changes invalidate previous reviews for activation.
This deliberately conservative reviewer-mandate rule is proposed staging behavior,
not a canonical production rule. Existing active rights are not automatically
revoked by a policy change; that requires a separate governed operation.

All evidence references and actor names remain synthetic fixture assertions.
No signature validation, independent review or real mandate issuance is claimed.
The test database owner can change mandates, policy and evidence directly.
`now` remains a caller-supplied test clock; an HTTP adapter must not accept it
from a client. No production authorization follows from these checks.

Verification: Python unittest, latest local execution on 2026-11-04. No remote CI run.
Connection reopen verifies persisted account/request data. v0.4 additionally tests
process exit after suspension commit, before audit delivery; this is not a power-loss test.

## v0.3 in-process intake contract

`intake.py` implements the review/activation request boundary described in
[HTTP-CONTRACT.md](HTTP-CONTRACT.md). `test_intake.py` adds 21 checks for synthetic
session/CSRF/origin validation, strict parsing, authority/time injection refusal,
stale bindings, failure rollback, separate actors and activation replay.
No network endpoint was added. This is synthetic session-bound evidence intake,
not authenticated evidence from a real reviewer. The underlying model has an
optional expected-binding argument for fixture compatibility; the adapter always
supplies it and the model checks it inside the write transaction.

AI review: TRIAS — no production route or runtime activation authority added.
ORACLE — 48 local tests support only this model/intake contract; OIDC, MFA and
human attestation remain NOT EXECUTED. MENTOR — address suspension/audit-failure
behavior next, before integrating any endpoint into the existing RIO service.
The SQLite file owner and trusted fixture code remain outside this threat model.

## v0.4 suspension outbox

Suspension commits `SUSPENDED` and an immutable outbox payload in one SQLite
transaction, then attempts audit delivery in a separate transaction. A failed
audit insert returns `AUDIT_PENDING`; the account remains blocked. Recovery
inserts the audit event and delivery receipt atomically. Concurrent retries do
not duplicate the event. Repeated suspension preserves original actor/time.
`pending_suspensions()` exposes outstanding recovery work to trusted fixture code;
no automatic worker, monitoring service, HTTP recovery route or operator alert
has been deployed. Callers must inspect the explicit pending result.

Twelve new tests cover ABORT and ROLLBACK audit failures, unauthorized actors,
outbox failure, immutable evidence, repeated requests, separate-process recovery,
process exit between durable block and audit, concurrent delivery and an activation
replay racing suspension during audit outage. A replay that serializes first may
return its earlier activation result; after suspension commits, access is denied.

Scope of guarantee: audit-table delivery failure after the first commit. The
outbox shares the account database. If the account/outbox commit fails (disk full,
write outage or outbox failure), suspension raises and must not be reported as
successful; prior ACTIVE state may remain. An independent runtime deny mechanism
and tested outage policy are still required before integration. Database file
owners remain outside the model threat boundary. Pending audit is not audit PASS.

AI review: TRIAS — block survives tested audit failures without production
activation. ORACLE — 60 local tests; no power-loss, real-session, PostgreSQL or
production evidence. MENTOR — define and test the runtime deny policy for total
storage failure before wiring the model to the RIO service. Production HOLD.

## v0.5 independent storage deny guard

[safety.py](safety.py) adds an opt-in GuardedModel facade with a separate
persistent SafetyStore. Full behavior and proof limits are in
[SAFETY-CONTRACT.md](SAFETY-CONTRACT.md). A durable account deny intent precedes
primary suspension; a primary storage error globally locks guarded access.
Fresh stores deny until explicit one-time fixture provisioning. Primary recovery
cannot unlock the circuit. Sixteen tests cover the new boundary; the existing
60 tests remain passing. The existing RIO service is not wired to this facade.

AI review: TRIAS — guarded refusal adds no production authority or reset route.
ORACLE — 76 local tests support the stated single-host fixture behavior, not
simultaneous failure of both stores, fleet enforcement or power-loss durability.
MENTOR — define restart fencing and authorized reconciliation next; do not wire
the facade into runtime before the remaining recovery gates are addressed.

## v0.6 per-start review fence

[restart.py](restart.py) adds RestartGuard, an opt-in per-process fence over the
safety facade. A new boot begins denied even with stale OPEN snapshots. Separate
fixture review and approval bind to boot/PID, a computed storage snapshot and a
maximum 30-second test lease. Reconciliation is required; existing locks are never
cleared. See [RESTART-CONTRACT.md](RESTART-CONTRACT.md) for the exact recovery
sequence, actor/evidence limits and unrecoverable-history boundary.

Nineteen new tests pass, including restoration of stale snapshots over both files
and separate-process startup. All 95 local tests pass. There is no real human
attestation, durable full boot-review archive, external history witness or RIO
runtime integration. Production and ACCOUNT-1 remain HOLD.

## v0.7 reproducible verification and evidence

Run both suites and produce source-bound, sanitized local evidence:

```sh
python verification/personal-account-control/verify.py --output work/account-evidence-new-run
python verification/personal-account-control/verify.py --check work/account-evidence-new-run
```

Use a fresh output path for each run. [EVIDENCE-CONTRACT.md](EVIDENCE-CONTRACT.md)
describes exact test inventory, source coverage, report semantics and unsigned
proof limits. The package contains only JSON and its digest, not raw logs or
runtime secrets. Production and ACCOUNT-1 remain HOLD. No commit, remote CI run,
RIO integration or real reviewer approval is claimed by this runner.

## v0.8 integrated disposable rehearsal

```sh
python verification/personal-account-control/rehearsal.py
```

This composes the intake and both guards over the model with disposable synthetic
storage. It checks 15 bounded outcomes; seven new tests exercise the integrated
path. [INTEGRATION-REVIEW.md](INTEGRATION-REVIEW.md) records the source review,
remaining commit-time session/expiry gates and the explicit distinction between
component integration and actual RIO runtime integration. The latter remains
NOT EXECUTED; production and ACCOUNT-1 remain HOLD. Generate a fresh verification
package after these changes; never relabel v0.7 evidence as current.

## v0.9 final session and expiry validation

[COMMIT-CONTRACT.md](COMMIT-CONTRACT.md) describes the new trusted commit guard,
local session/revocation serialization and explicit authorization linearization
point. Review and activation recheck session, boot lease, mandates and relevant
expiry after database lock waits and after writes, before COMMIT. Refusal rolls
back all transaction changes. Direct fixture model calls retain their optional
callback behavior; actual serving must not bypass the outer stack.

Ten new tests exercise real two-connection lock waits and failure after writes.
All 127 slice tests plus the 8 existing gate tests pass. Real OIDC, distributed
revocation and RIO runtime wiring remain NOT EXECUTED; production/ACCOUNT-1 HOLD.

## v0.10 RIO refusal-boundary candidate

[OIDC-BRIDGE-CONTRACT.md](OIDC-BRIDGE-CONTRACT.md) records the inspected OIDC
session seam, the candidate additive /api/me metadata and the refusal-only Python
classifier. Successful identity verification remains UNKNOWN for strong-auth
purposes and never seeds an activation-capable session. Six new Python tests and
one standalone Rust module test pass. Full service build/router/OIDC execution is
blocked by missing axum and unreachable crates.io; this candidate is not deployed.
The verifier now hashes the RIO Rust sources, SQL migrations and Cargo files too,
while explicitly recording rioServiceTests NOT_EXECUTED. Its PASS covers only
its two named Python suites. Production and ACCOUNT-1 remain HOLD.

## v0.11 existing synthetic CI route

[CI-CONTRACT.md](CI-CONTRACT.md) records the new path triggers and verification
step in the existing RIO synthetic workflow. The complete existing Rust/OIDC/
PostgreSQL/browser sequence remains mandatory. No remote workflow was dispatched
or observed, and the local full-service build remains dependency/network-blocked.
The local evidence runner additionally binds the workflow's exact source bytes.
Python/standalone-module success is not promoted to full-service or CI PASS.

## v0.12 reviewable source overlay

[bundle.py](bundle.py) builds/checks a new unsigned ZIP from current passing
evidence and an explicit source allowlist. [BUNDLE-CONTRACT.md](BUNDLE-CONTRACT.md)
describes exact contents, base-checkout requirements and review/CI steps. Embedded
RIO web assets are now source-bound too. Four new archive checks bring the local
slice to 137 tests plus 8 existing review-gate tests. No archive generation publishes
or executes the candidate, and full-service verification remains network-blocked.

## v0.13 current-main overlap reconciliation and public PR plan

Connected GitHub reads found main 18 commits ahead of the local base. The shared
workflow was merged locally with pinned upstream changes; its three readback/
mobile prerequisites were copied with exact Git blob parity and source-bound.
[PUBLICATION-PLAN.md](PUBLICATION-PLAN.md) records both bases, verification limits,
the concrete proposed public branch/draft PR and the permission boundary.
The local HEAD is not rebased and no remote write or CI dispatch has occurred.
Full RIO Rust and upstream Playwright checks remain dependency-blocked. New local
evidence and review overlay supersede neither the old artifacts nor remote CI.

## v0.14 real CI regression correction

[CI-BOUNDARY-FIX.md](CI-BOUNDARY-FIX.md) records the first actual RIO CI result:
Rust/build/storage checks passed, but the new response field was incompatible
with the frontend and browser exact schemas. The corrected consumers still
require the exact refusal boundary. Existing real-browser coverage now rejects
malformed/promoted metadata and checks recovery to the genuine response. New
head/run evidence is required; old success/failure records are not rewritten.
