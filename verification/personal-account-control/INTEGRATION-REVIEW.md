# Integrated synthetic slice v0.1 — source review and rehearsal

Object: Personal Account Control reference model v0.8, local uncommitted bytes.
Review basis: model.py, intake.py, safety.py, restart.py, verify.py and their tests.
Reviewer: one assistant using three lenses; no independent human sign-off.
Prior evidence remains unchanged; v0.7 evidence is historical, not evidence for
these changed source bytes. Current evidence must be freshly generated.

## Concrete integration

`rehearsal.py` composes Intake → RestartGuard → GuardedModel → Model, with separate
primary/safety SQLite files, synthetic session actors and a trusted fixture clock.
Only disposable temporary files are used; sessions and databases are removed at
normal cleanup. No listener, TLS endpoint, OIDC provider, email, real account,
clinical data, production resource or RIO service module is touched.

Run the bounded integrated scenario:

```sh
python verification/personal-account-control/rehearsal.py
```

It emits 15 fixed boolean outcomes and explicit synthetic/HOLD boundaries; no
raw actor credentials, session tokens, CSRF values, storage snapshots or logs.
Seven integration tests additionally exercise session revocation before a request,
boot expiry with a valid session, fresh-fence adapter denial, client injection and
primary-storage failure through the complete adapter/guard stack.

The scenario includes review/activation separation, a fresh *fence instance*
requiring new approval, audit-outage suspension, replay refusal and audit
reconciliation without account reactivation. This scenario does not restart a
process; separate-process tests remain in test_restart.py/test_suspension.py.
It auto-selects synthetic fixture approvals, never human decisions.

## Source findings and integration gates

| Finding | Evidence in code | Consequence |
| --- | --- | --- |
| Session is resolved once at intake | Intake.handle resolves before JSON/model calls | Real runtime BLOCKED until session revocation/expiry is rechecked at the commit boundary with a defined concurrency contract |
| Current time is checked before potentially blocking storage operations | RestartGuard.ready and Model.activate use passed time before/between lock acquisition | Real runtime BLOCKED until commit-time expiry behavior is defined and tested under delayed lock acquisition |
| Inner model/guard can be called directly by trusted code | Fixtures intentionally exercise Model and GuardedModel | All real serving routes would need enforced outer-guard wiring and bypass tests; not established here |
| Boot approvals use configured fixture roles | RestartGuard roles are a local immutable mapping | No claim of real reviewer identity, live mandate revocation, MFA or human authorization |
| Both restored stores may have lost history | test_restart stale-snapshot case | Startup denial is proved; historical completeness and external restore attestation are not |
| Recovery cannot unlock global/account safety latches | safety.py has no release/reset operation | This remains a safe refusal; operational recovery needs a separately governed contract |

No critical finding is waived by passing tests. The fixes above belong to a
future source revision with new evidence; they are not implemented by the demo.

## Review outcome

TRIAS: GO for this disposable synthetic composition only. Production/account
activation authority stays NONE; ACCOUNT-1 and production HOLD.
ORACLE: real local tests and a fresh source-bound unsigned package support the
stated component behavior. Real session races, service integration and external
authority are NOT VERIFIED. No multi-reviewer or remote CI claim.
MENTOR: next concrete slice should implement and test commit-time session/expiry
validation before any network adapter or RIO route wiring is proposed.

## v0.9 follow-up — bounded findings addressed

COMMIT-CONTRACT.md records the local final-validation implementation and ten new
regression tests for the session/expiry findings above. They are addressed for
the integrated synthetic single-process path. Distributed session revocation,
real OIDC authority, wall-clock completion deadlines and enforced real-route
wiring remain outside this proof. This does not retroactively change v0.8 tests
or evidence and does not promote the slice to production-ready.
