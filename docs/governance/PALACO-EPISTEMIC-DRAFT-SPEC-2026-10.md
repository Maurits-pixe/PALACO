# PALACO epistemic draft specification

**Status:** DRAFT / non-canonical / unverified  
**Branch:** palaco-epistemic-draft-specs-20261007  
**Date:** 2026-10-07

This is the next GO's concrete contract proposal for ETCG, KESG, KAG, Linnaeus/HORTUS, source independence, conflict and revalidation. It is a review artifact. It does not amend the Constitution, create authority, change a runtime API, or certify a gate.

## Shared invariants

1. A classification describes what a subject is; it does not say what the subject may do.
2. Evidence, adequacy, governance, authorization and execution remain separate layers.
3. A state change appends a transition record; it never silently rewrites state, time or history.
4. STALE is not FALSE; VERIFIED is scoped to a purpose and context.
5. RIO is the river/communication surface and remains distinct from ELIXER.
6. Human-facing VORM9EVIN9 must preserve the exact semantic distinction between observed, proposed, determined, verified, approved and authorized.
7. QUAY stores the reconstructable record; it does not decide truth or grant authority.
8. CI, evidence and verification are scoped results and do not automatically authorize runtime execution.

## Candidate knowledge lifecycle

~~~text
REALITY (external)
  -> OBSERVATION
  -> EVIDENCE
  -> FEATURE / COMPARISON
  -> DETERMINATION
  -> CLASSIFICATION
  -> EPISTEMIC STATUS
  -> PROVENANCE + SOURCE LINEAGE
  -> KESG (evidence sufficiency)
  -> KAG (purpose adequacy)
  -> ETCG (state transition)
  -> GOVERNANCE DECISION
  -> AUTHORIZATION (only when separately available)
  -> BOUNDED EXECUTION
  -> QUAY HISTORY
~~~

The arrow is a review order, not an authority chain. A failed or indeterminate step blocks or defers the next step. A successful step cannot skip governance.

## Candidate state vocabulary

The following vocabulary is a draft for review, not a required linear ladder:

~~~text
Unknown
Observed
Proposed
Supported
Corroborated
Determined
Verified
Disputed
Contradicted
Conflicted
Stale
Superseded
Rejected
InDoubt
~~~

The graph is rule-governed. Unknown to Verified is not accepted without the required basis, but an approved external verification may allow a different valid edge than a local observation. A contrary opinion alone cannot downgrade a verified claim; repetition alone cannot upgrade it.

## ETCG candidate

ETCG evaluates a requested material state transition.

~~~text
TransitionRequest
  subject
  previous_state
  requested_state
  trigger
  evidence_refs
  temporal_context
  purpose_context
  provenance_ref
  rationale
~~~

ETCG checks that the prior state is addressable, the trigger is recognized but not treated as a determination, evidence and provenance are present, temporal and purpose context are explicit, contradictions and identity conflicts are represented, the proposed edge is allowed, and the decision is append-only and replayable.

The resulting EpistemicTransition contains an immutable transition ID, prior state, new state, trigger, evidence references, rationale, effective time, decision and provenance. The previous record remains readable. This draft does not define a database, event format or authorization capability.

## KESG candidate

KESG asks whether evidence is sufficient for the declared claim and context.

Candidate dimensions:

~~~text
EvidenceCompleteness
SourceValidity
ProvenanceCompleteness
TemporalValidity
ContradictionCoverage
IdentityCoverage
MethodValidity
~~~

Candidate outcomes:

~~~text
Sufficient
Insufficient
ConditionallySufficient
Stale
Conflicted
InDoubt
~~~

A missing critical dimension yields Insufficient or InDoubt; dimensions may not be averaged into a misleading pass. KESG does not determine truth and does not authorize action.

## KAG candidate

KAG asks whether the available knowledge is adequate for the intended use.

Candidate dimensions:

~~~text
PurposeAdequacy
ScopeAdequacy
ConsequenceAdequacy
ContextAdequacy
TemporalAdequacy
VerificationAdequacy
EvidenceAdequacy
~~~

A critical-dimension veto is mandatory. Adequate means adequate for this declared use and consequence profile; it never means permitted. KAG may require revalidation or governance review but cannot produce authorization.

## Linnaeus/HORTUS candidate

Linnaeus/HORTUS is a living epistemic and taxonomic model:

~~~text
Identity
Determination
Classification
Context
State
Relations
Lineage
TemporalSnapshot
Evidence
Provenance
Uncertainty
Conflict
~~~

HORTUS may observe drift and expose relations. It must preserve:

~~~text
OBSERVATION != REALITY
DETERMINATION != CLASSIFICATION
CLASSIFICATION != AUTHORITY
CAPABILITY != AUTHORIZATION
~~~

A material classification has an effective time, basis and provenance. A reclassification does not destroy historical identity or a prior snapshot. InDoubt, Conflicted and InsufficientEvidence remain representable.

## Source independence

Corroboration is not a count of documents. A candidate source record carries a source ID, source lineage, parent source IDs, extraction method, transformation history and independence assessment.

Candidate independence values:

~~~text
Independent
PartiallyIndependent
DerivedFromExistingEvidence
SameSource
Unknown
~~~

The system must not infer independence from separate URLs, domains, authorship labels or repeated wording. Unknown remains a valid result.

## Conflict and revalidation

A candidate EpistemicConflict preserves both or all incompatible assertions. Its record contains a conflict ID, subject reference, assertion references, evidence references, conflict type, detection time, optional resolution reference and provenance.

Candidate conflict types include factual, temporal, identity, classification, source, scope, method, constitutional and capability. Identity conflict is handled before unsafe classification. Resolution links to a new determination; it does not delete conflicting records.

Revalidation is triggered by changed evidence, revoked sources, changed context/scope/purpose, time expiry, capability change, increased risk, detected drift or contradiction. Revalidation creates a new assessment and preserves the previous one.

## HRAEG and ambassador model boundary

HRAEG and the seven-ambassador/HOOFDKANTOOR model remain governance proposals. This draft defines no grant.

Before any future implementation, the source audit must identify the constitutional provision that grants recognition or grant authority; identity and role proof; consent, quorum, veto, appointment and revocation rules; temporal bounds; evidence and provenance requirements; separation between HOOFDKANTOOR ownership, council membership and decision authority; and denial, timeout, abstention and missing-vote behavior.

A council cannot vote itself into authority. A 5/7 or 7/7 result is not meaningful until a constitutional source defines what that vote can decide.

## Candidate negative fixtures (unexecuted)

These IDs are proposed review cases, not passing tests:

- EPI-101: direct label overwrite is rejected;
- EPI-102: a transition without provenance is rejected;
- EPI-103: stale evidence cannot satisfy a time-critical purpose;
- EPI-104: repeated copies do not become independent corroboration;
- EPI-105: contrary opinion alone does not create contradiction;
- EPI-106: identity conflict blocks unsafe classification;
- EPI-107: conflict records remain replayable after resolution;
- EPI-108: KESG insufficiency does not become KAG adequacy;
- EPI-109: KAG adequacy does not become authorization;
- EPI-110: CI/evidence success does not create runtime permission;
- EPI-111: RIO and ELIXER labels remain distinct;
- EPI-112: VORM9EVIN9 does not compress distinct constitutional states.

All cases require inspectable fixtures and evidence before any later ratification claim.

## Review outcome

This specification is deliberately additive and non-authorizing. It is ready for source review and fixture design, not for constitutional sealing, public API implementation, runtime deployment or merge.
