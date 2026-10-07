# GO-044 — L.A. ExecutionReceipt + Observation Boundary

## Constitutional position

The L.A. execution chain now distinguishes:

AUTHORIZATION → EXECUTION PERMIT → EXECUTION → EXECUTION RECEIPT → OBSERVATION → CONSEQUENCE / REASSESSMENT

An ExecutionReceipt records what happened to an authorized execution request. It does not create authority and does not prove that the requested outcome was achieved.

An ObservationReceipt records an observed post-execution state and its provenance basis. It does not rewrite the ExecutionReceipt.

## Rules

- EXECUTION RECEIPT != EXECUTION PERMIT
- OBSERVATION != EXECUTION
- EXECUTION SUCCESS REQUIRES OBSERVATION
- UNKNOWN EXECUTION OUTCOME => FAIL_CLOSED
- DECISION != AUTHORIZATION
- AUTHORIZATION != EXECUTION
- SIGNATURE != AUTHORITY
- PROVENANCE != PERMISSION

## Implementation

- ExecutionReceipt is constructible only from an ExecutionPermit.
- Receipt status is explicit: NotStarted, Started, Completed, Failed, Partial, Cancelled, Unknown.
- ObservationReceipt requires a source and observation method to be considered usable.
- Before/after state, evidence references and contradictions remain explicit.
- Observation is additive history; it does not mutate prior execution history.

## Non-goals

GO-044 does not introduce an executor, does not infer success from a Decision or Authorization, and does not grant RIO authority.

## Verification status

Source implementation is complete. CI must be verified from an actual GitHub Actions run before GREEN is claimed.
