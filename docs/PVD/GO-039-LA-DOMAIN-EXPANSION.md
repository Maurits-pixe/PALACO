# GO-039 — L.A. Evidence / Question / Epistemic / Threshold Domain Expansion

Status: IMPLEMENTED — CI verification pending.

## Constitutional chain

QUESTION → CONTEXT → EVIDENCE → EPISTEMIC STATE → THRESHOLD → DECISION

This slice deliberately stops before authorization and execution.

## Domain objects

- Question: identifies the subject and contextual frame.
- Evidence: records source/origin, content digest, relevance, limitations and epistemic status.
- EpistemicState: explicitly separates known, unknown and disputed material and records assumptions, contradictions and limitations.
- ThresholdAssessment: records the evidence basis and whether the decision threshold is explicitly satisfied.
- Decision: remains distinct from authorization and execution.

## Fail-closed rules

- EpistemicStatus::Unknown is never silently promoted to usable evidence.
- A threshold permits a decision only when its state is explicitly Satisfied.
- An Allow decision may be authorizable, but does not itself execute anything.
- Existing constitutional boundaries remain explicit: ACCESS != AUTHORIZATION, DECISION != EXECUTION, SIGNATURE != AUTHORITY, PROVENANCE != PERMISSION.

## Non-goals

This GO does not introduce authority mutation, execution, RIO authority, PostgreSQL projections, or intelligence-derived authorization.
