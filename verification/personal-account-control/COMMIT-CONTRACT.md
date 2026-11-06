# Final authorization check v0.1 — synthetic single-process contract

Object: reference model v0.9. No actual RIO/OIDC runtime is wired.

Intake passes a trusted commit_guard context manager down through RestartGuard
and GuardedModel into Model.review/activate. Model.transaction invokes it after
all writes, immediately before issuing COMMIT. If it refuses, the transaction
rolls back status, review evidence, request/idempotency and audit changes together.

At that boundary:

- Intake rereads the trusted clock and resolves the same opaque session again.
  The session must still exist, be strong in fixture terms, match the original
  immutable session record and remain unexpired. Clock rollback refuses.
- The session registry RLock stays held through COMMIT. Seed/revoke/resolve use
  the same lock. A revocation that completes first prevents commit; a commit
  whose final validation wins may finish before the concurrent revoke returns.
- RestartGuard rechecks PID, clock, current boot lease and fixture role mapping.
- Model rechecks account binding and current actor mandate, including expiry.
  Activation also rechecks reviewer mandate and review-evidence expiry; requested
  review/activation expiry must still lie in the future.

Lock order is runtime guard → safety SQLite → primary SQLite → session registry.
Initial intake session lookup releases its lock before entering runtime code.
The revocation method acquires only the session lock. Trusted callbacks must not
introduce a reverse order or mutate the same transaction behind this contract.

The authorization linearization point is the final validation protected by the
session lock. This is not a hard real-time guarantee about when the disk finishes
COMMIT: filesystem delays or SQLite commit waits may occur afterward. The clock
is a trusted fixture dependency; production needs an explicit wall-clock and
session-authority design. No distributed revocation or OIDC/MFA proof is claimed.

Direct Model fixture calls retain optional commit_guard compatibility and use
their passed test time when none is supplied. Every serving adapter must use the
complete Intake/RestartGuard path; bypassing it bypasses these new guarantees.
No callback can be selected or submitted by client JSON.

## Executed controls

Ten new tests cover:

1. Review-session revocation during a real primary write-lock wait.
2. Activation-session revocation during that wait.
3. Session expiry during that wait.
4. Boot lease expiry during that wait.
5. Review evidence expiry during that wait.
6. Mandate expiry during that wait.
7. Revocation after an audit write, before review commit, with full rollback.
8. Requested activation expiry after writes, with rollback.
9. Requested review expiry after writes, with rollback.
10. Clock/session expiry after activation writes, with rollback.

The existing full rehearsal remains passing. No previous test was removed from
the fixed inventory. Evidence must be generated anew for this revision.

AI review: TRIAS — no production routes, authority or release change. ORACLE —
these local interleavings establish the single-process fixture ordering above,
not distributed session semantics or physical commit deadlines. MENTOR — the
next gate is a reviewed shared-session/OIDC adapter contract and enforced outer
route wiring; real RIO integration stays NOT EXECUTED and production HOLD.
