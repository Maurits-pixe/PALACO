# ∆ GO-042 — L.A. AUTHORITY / AUTHORIZATION BOUNDARY

Status: IMPLEMENTED — CI verification pending.

## Constitutional chain

QUESTION → CONTEXT → EVIDENCE → EPISTEMIC STATE → THRESHOLD → DECISION
→ AUTHORITY → AUTHORIZATION → EXECUTION

GO-042 introduces the first explicit boundary between a Decision, an Authority and an Authorization.

## Rules

- A Decision is not an Authority.
- An Authority is not an Authorization.
- An Authorization is not an Execution.
- A Decision can only enter authorization evaluation when its verdict is explicitly `Allow`.
- Authority must be `Active`.
- Requested authorization scope must be contained by the Authority scope.
- Revoked, suspended or expired Authority cannot produce Authorization.
- Scope expansion is rejected fail-closed.
- Cryptographic validity does not create Authority.
- Provenance does not create Permission.

## Scope containment

Authorization scope is never allowed to exceed the governing Authority:

`requested_scope ⊆ authority_scope`

The current implementation requires exact target, territory and purpose matching, with requested operations being a subset of the Authority operations.

## Decision hardening

The previous `Decision::can_authorize()` convenience method has been removed. Decisions expose `is_allow()` only; creation of Authorization is exclusively performed through the explicit authorization evaluator.

This prevents the domain object itself from being interpreted as an authority transition.

## Non-goals

GO-042 does not implement:

- execution;
- execution permits;
- consent lifecycle;
- revocation propagation;
- temporal validity based on timestamps;
- HTTP/API mutation;
- RIO authority.

Those remain separate constitutional boundaries.

## Verification gate

The implementation is source-level complete for GO-042. CI remains the authoritative compilation/test/clippy gate.

Last verified GREEN baseline: GO-038.
