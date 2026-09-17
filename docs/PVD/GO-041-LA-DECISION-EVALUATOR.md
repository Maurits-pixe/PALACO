# GO-041 — L.A. Decision Evaluator

Status: IMPLEMENTED — CI verification pending.

## Constitutional chain

QUESTION → CONTEXT → EVIDENCE → EPISTEMIC STATE → THRESHOLD → DECISION

GO-041 introduces the first explicit decision evaluator. A decision can only be produced when the threshold is explicitly `Satisfied` and every Evidence item named by the threshold basis exists, belongs to the Question, and is usable.

## Fail-closed conditions

- threshold not satisfied → no Decision
- missing threshold Evidence → no Decision
- unusable Evidence → no Decision
- cross-question Evidence → no Decision
- Unknown Evidence cannot support a Decision

## Authority boundary

The evaluator creates a `Decision`, not an `Authorization` and not an execution permit. A Decision does not mutate authority and does not execute an action.

## Next boundary

DECISION → AUTHORITY → AUTHORIZATION remains a separate constitutional layer.
