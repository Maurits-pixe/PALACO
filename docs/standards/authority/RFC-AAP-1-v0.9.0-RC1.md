# RFC-AAP-1: Authority Assignment Protocol

## Document status

| Field | Value |
|---|---|
| RFC ID | RFC-AAP-1 |
| Protocol | AAP-1 |
| Title | Authority Assignment Protocol |
| Version | 0.9.0-RC1 |
| Status | Review Candidate |
| Category | Constitutional Governance Specification |
| Parent specifications | ACCOUNT-1, IIP-1 |
| Canonical adoption | Pending |
| Implementation status | Partial · synthetic lifecycle event validator only |
| Operational authority effects | None |

This document is a review candidate, not an adopted PALACO canon or a deployed
authority service. Completeness of this draft does not imply canonical adoption.

## Abstract

AAP-1 specifies a proposed constitutional process for assigning bounded
authority to an identity that has already been issued. It distinguishes
authentication, identity issuance, authority assignment, execution
authorization, and execution. It describes request and decision records,
review gates, grant state, lifecycle, registries, revocation, and acceptance
criteria.

AAP-1 does not authenticate actors, issue identities, authorize a particular
execution, execute actions, or itself establish the constitutional bootstrap
authority required to approve the first grant issuer. Those boundaries require
separate protocols, decisions, and implementations.

## 1. Problem statement

PALACO's authority model requires that membership, federation, custody,
evidence, and identity do not independently create authority. Without a
separate authority-assignment protocol, implementations can collapse
authentication, identity, role assignment, and execution into one implicit
trust chain.

AAP-1 defines a reviewable process intended to prevent that collapse.

## 2. Objectives and non-objectives

AAP-1 SHALL define requirements for:

- requesting and reviewing constitutional authority grants;
- establishing constitutional basis and granting authority;
- scoping, validity, review, suspension, and revocation;
- recording decisions, grants, lifecycle changes, and audit evidence; and
- evaluating a grant's current effectiveness independently of execution.

AAP-1 SHALL NOT:

- authenticate an actor or establish control of an account;
- issue, validate, or revoke an identity (IIP-1 boundary);
- make an approval equivalent to an issued grant;
- make a grant equivalent to effective authority;
- authorize or execute a specific operation; or
- treat AI advice, recommendation, scoring, or prediction as approval.

## 3. Architectural context

```text
ACCOUNT-1
  Authentication
       ↓
IIP-1
  Identity issuance
       ↓
AAP-1
  Authority assignment and lifecycle
       ↓
Separate authorization review
       ↓
Execution-time revalidation
       ↓
Execution
       ↓
Evidence → Provenance → Audit → Replay → State → Seal
```

The diagram describes separate responsibilities, not an implemented service
chain. AAP-1 ends at determining whether an authority grant is currently
effective. Execution systems remain responsible for their own authorization
decision and execution controls.

## 4. Scope

AAP-1 applies exclusively to constitutional authority grants, for example:
issuer, custodian, steward, operator, auditor, reviewer, or governor.

Ordinary account activity—such as login, logout, profile updates, password
changes, session management, and preferences—is outside AAP-1 and remains
governed by ACCOUNT-1 and applicable authorization policy unless an adopted
policy explicitly elevates an operation into constitutional authority scope.

## 5. Normative terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as normative
requirements within this review-candidate specification. They do not override
the pending canonical-adoption status.

## 6. Preconditions

Authority review MUST NOT begin unless:

1. The subject has an `IDENTITY_ISSUED` record under IIP-1.
2. The identity is not `REVOKED`, `SUSPENDED`, or `EXPIRED`.
3. An explicit Authority Request Record (ARR) exists.

Authentication, account activation, provisional dossier status, or a
5CRIPTIE/administrative identifier MUST NOT substitute for an issued identity.
An authority review MUST NOT be initiated implicitly.

## 7. Authority Request Record

Every request MUST create a durable, uniquely identifiable ARR. It SHOULD
contain at least:

```text
ARR
├── request_id
├── identity_ref
├── authority_type
├── requested_scope
├── justification
├── evidence_refs
├── requester_ref
├── policy_version
├── requested_validity
└── status
```

The request record MUST preserve the requested authority and scope as
submitted. Subsequent review MUST NOT silently broaden or rewrite the request.
Changes to the request require a new version or a new request linked to the
prior record.

## 8. Constitutional basis review

The review MUST determine whether an identifiable constitutional basis permits
the requested authority type and scope.

Outcomes:

- `CONSTITUTIONAL_BASIS_FOUND`
- `CONSTITUTIONAL_BASIS_MISSING`

Missing, ambiguous, or untraceable basis MUST prevent approval and grant
issuance.

## 9. Granting authority review

The review MUST establish that the proposed issuer has current authority,
independent of the request, to grant the exact authority type and requested
scope.

Outcomes:

- `GRANTING_AUTHORITY_CONFIRMED`
- `GRANTING_AUTHORITY_REJECTED`

Granting authority MUST NOT be derived from the request, requested role,
beneficiary identity, or grant being considered. The issuer's authority and
scope MUST be independently verifiable at decision time.

## 10. Bootstrap authority

The first grant issuer presents a bootstrap question: who authorizes the
initial grant-making authority? Under this proposal, bootstrap authority MUST
originate in a separately recorded constitutional decision with its own
constitutional basis and evidence.

It MUST NOT be inferred from convention, repository ownership, import,
implementation privilege, operational convenience, or assumption.

This section does not identify or appoint a bootstrap authority. The
constitutional decision mechanism, decision-maker, evidence requirements, and
verification method remain adoption blockers. No initial grant issuer is
authorized by this RFC.

## 11. Scope review

Each proposed grant MUST specify:

- authority type;
- bounded scope and resource class;
- validity period;
- review authority and interval, or an explicit non-reviewable basis; and
- revocation and suspension behavior.

Undefined scope, unlimited scope, infinite validity, and implicit scope
expansion MUST be rejected.

Outcomes:

- `SCOPE_ACCEPTED`
- `SCOPE_REJECTED`

## 12. Evidence review

The decision MUST be supported by traceable evidence appropriate to the
request. Evidence SHOULD include the ARR, current identity state, applicable
constitutional and policy references, supporting material, and relevant
historical decisions.

Outcomes:

- `AUTHORITY_EVIDENCE_ACCEPTED`
- `AUTHORITY_EVIDENCE_INSUFFICIENT`

An evidence digest alone is insufficient unless its source state and
provenance can be identified and reviewed. Missing, stale, disputed, or
unverifiable evidence MUST NOT support approval.

## 13. Conflict and separation-of-duties review

Review MUST evaluate, where applicable:

- privilege escalation;
- self-grant;
- self-review and self-audit;
- custody, issuer, and reviewer conflicts; and
- separation-of-duties violations.

Outcomes:

- `CONFLICT_FREE`
- `CONFLICT_PRESENT`

Conflicts that policy does not explicitly permit and mitigate MUST block
approval. The beneficiary MUST NOT be the sole approver of their own grant.

## 14. WISDOM review

The request MUST pass the applicable WISDOM process defined by the relevant
adopted policy.

Outcomes:

- `WISDOM_REVIEW_COMPLETED`
- `WISDOM_REVIEW_FAILED`

AI advice, recommendation, scoring, or prediction MUST NOT by itself constitute
WISDOM approval. This RFC does not define a universal WISDOM procedure; the
applicable process and evidence MUST be identified by policy.

## 15. Authority Decision Record

Every outcome—`APPROVED`, `DENIED`, or `HOLD`—MUST create a durable,
attributable Authority Decision Record (`AUTH-DEC`).

```json
{
  "decision_id": "AUTH-DEC-000001",
  "request_id": "ARR-000001",
  "decision": "APPROVED | DENIED | HOLD",
  "issuer_ref": "reviewing-authority-reference",
  "policy_version": "policy-version",
  "evidence_bundle_ref": "evidence-bundle-reference",
  "reason": "decision rationale",
  "timestamp": "RFC-3339 timestamp"
}
```

The record MUST link to the exact request, policy version, evidence bundle,
review outcome, and decision-maker identity. A decision record documents an
outcome; it does not itself issue a grant or create authority.

## 16. Authority states

AAP-1 distinguishes:

- **APPROVED** — a valid constitutional decision permits issuance of a bounded
  grant.
- **GRANTED** — a grant object has been issued and durably registered against
  that decision.
- **EFFECTIVE** — the registered grant is currently valid, in scope, not
  suspended or revoked, and compliant with its review requirements.

Therefore:

```text
APPROVED ≠ GRANTED ≠ EFFECTIVE
```

An approval MUST NOT be represented as a grant. A grant MUST NOT be represented
as effective without a current effectiveness check.

## 17. Authority Grant Object

Only after an `APPROVED` AUTH-DEC may a grant object be issued. It MUST be
durably registered and linked to the decision and evidence.

```json
{
  "grant_id": "AG-000001",
  "identity_ref": "issued-identity-reference",
  "authority_type": "bounded-authority-type",
  "scope": "explicit-bounded-scope",
  "issued_by": "authorized-issuer-reference",
  "decision_ref": "AUTH-DEC-000001",
  "evidence_ref": "evidence-bundle-reference",
  "valid_from": "RFC-3339 timestamp",
  "valid_until": "RFC-3339 timestamp",
  "review_due": "RFC-3339 timestamp",
  "revocation_epoch": 1
}
```

The object MUST NOT be treated as authority solely because it is syntactically
valid, signed, sealed, or present in a registry.

## 18. Registry model

The proposal requires four logically distinct, durable registries:

1. **Authority Grant Registry** — grant objects, current state, and immutable
   grant history.
2. **Authority Decision Registry** — AUTH-DEC records and their request,
   evidence, policy, and reviewer bindings.
3. **Authority Revocation Registry** — revocations, suspensions, and
   reinstatement decisions.
4. **Authority Audit Registry** — lifecycle events, review evidence, and
   attributable audit records.

The registries MAY share a storage implementation, but MUST preserve the
logical separation, provenance, integrity, and queryability of each record
class. Updates MUST be append-only or otherwise preserve reconstructable
history; prior decisions and lifecycle events MUST NOT be silently overwritten.

Registry schemas, consistency guarantees, retention, access controls, and
recovery behavior are not defined by this RC and remain implementation and
adoption gates.

## 19. Lifecycle, suspension, and revocation

Grant lifecycle states are:

- `EFFECTIVE`
- `UNDER_REVIEW`
- `SUSPENDED`
- `REVOKED`
- `EXPIRED`

`REINSTATED` is a recorded transition, not a grant state. Reinstatement from
`SUSPENDED` requires a new attributable decision, current evidence, and
revalidation of scope and validity. A revoked grant MUST NOT be reinstated;
any renewed authority requires a new request and grant.

Examples of permitted transitions:

```text
EFFECTIVE → UNDER_REVIEW → EFFECTIVE
EFFECTIVE → SUSPENDED → [REINSTATEMENT DECISION] → EFFECTIVE
EFFECTIVE → REVOKED
EFFECTIVE → EXPIRED
```

Every transition MUST have a timestamp, actor, reason, evidence references, and
registry update. Unknown or invalid transition history MUST fail closed.

### 19.1 Reference lifecycle validator

`palaco-la::authority_assignment::validate_lifecycle_event` implements a
synthetic, pure validation of proposed transition shape. It checks the
transition/decision pairing, required identifiers and evidence references,
RFC-3339 event timestamps, monotonic ordering, and that an event is not from
the future. Revoked and expired states are terminal; suspension can return to
effective only through an explicit reinstatement decision.

`validate_lifecycle_history` additionally checks a supplied ordered list of
events for consistent grant references, contiguous state transitions, and
monotonic event time from a supplied starting state. Both the starting state
and events remain caller assertions; this check does not load or authenticate a
registry history.

The function does not authenticate an actor, evidence, decision, or prior
registry state. It does not append an event, change grant state, issue or revoke
a grant, or determine that any authority is effective. Production AAP-1
implementation remains unimplemented; acceptance and adoption gates remain
open.

## 20. Effective-authority criteria

A grant is `EFFECTIVE` only if all of the following are established from current
state:

- an approving AUTH-DEC exists;
- the grant exists and is registered;
- identity and grant are valid at evaluation time;
- the requested resource and operation fall within the grant scope;
- the grant is not revoked, suspended, or expired; and
- required reviews are current and complete.

Reviewable grants MUST define the review authority, interval, and failure
behavior. If a required review is missed or cannot be verified, the grant MUST
become ineffective; policy MAY require suspension.

## 21. Authority seal

A grant MAY be sealed using an approved canonical encoding and digest process:

```text
Authority Grant → Canonical Encoding → Digest → Authority Seal
```

A seal identifies or detects changes to the sealed object. A seal MUST NOT
create, grant, expand, or prove the current effectiveness of authority:

```text
AUTHORITY SEAL ≠ AUTHORITY
```

This RC does not select a canonical encoding, signing profile, key lifecycle,
or verification trust anchor.

## 22. Execution boundary and revalidation

AAP-1 terminates at the determination of `EFFECTIVE AUTHORITY`. It does not
authorize a specific operation or trigger execution.

Separate authorization MUST evaluate, as applicable, the current actor,
session, authority, scope, policy, consent, resource, and revocation state.
Immediately before execution, the execution system MUST revalidate current
authority, scope, policy, validity, consent, and revocation state. Historical
approval or a cached grant alone is insufficient.

Authorization MUST NOT by itself trigger execution or prove that execution
occurred. Execution requires its own bounded control and attributable receipt.

## 23. Acceptance criteria

Canonical adoption MUST NOT occur until automated, reviewable tests demonstrate
at least:

- self-grant rejection;
- self-review rejection;
- rejection without constitutional basis;
- rejection without sufficient evidence;
- rejection without an AUTH-DEC;
- expired grant is ineffective;
- revoked grant is ineffective;
- suspended grant is ineffective;
- scope escalation is rejected;
- bootstrap authority is validated against a separate decision; and
- execution-time revalidation is required.

Tests MUST include valid and invalid transitions and verify that an unknown,
stale, or unavailable trust input fails closed.

## 24. Canonical invariants

```text
NO EFFECTIVE AUTHORITY
WITHOUT CONSTITUTIONAL BASIS.

NO AUTHORITY GRANT
WITHOUT ISSUED IDENTITY.

NO AUTHORITY GRANT
WITHOUT EXPLICIT AUTHORITY REQUEST.

NO AUTHORITY GRANT
WITHOUT CURRENT, SCOPED GRANTING AUTHORITY.

NO AUTHORITY OUTCOME
WITHOUT RECORDED DECISION.

NO AUTHORITY GRANT
WITHOUT TRACEABLE EVIDENCE.

NO AUTHORITY GRANT
WITHOUT DEFINED SCOPE.

NO AUTHORITY GRANT
WITHOUT REVOCATION CAPABILITY.

AUTHORITY GRANTS SHALL BE
TIME-BOUND OR EXPLICITLY REVIEWABLE.

AI ADVICE SHALL NOT,
BY ITSELF,
CONSTITUTE WISDOM APPROVAL.

APPROVAL SHALL NOT,
BY ITSELF,
CONSTITUTE A GRANT.

A GRANT SHALL NOT,
BY ITSELF,
CONSTITUTE EFFECTIVE AUTHORITY.

EFFECTIVE AUTHORITY
SHALL REQUIRE CURRENT VALIDITY,
CURRENT SCOPE,
AND CURRENT NON-REVOCATION.

AN AUTHORITY GRANT SHALL NOT,
BY ITSELF,
AUTHORIZE A SPECIFIC EXECUTION.

AUTHORIZATION SHALL NOT,
BY ITSELF,
TRIGGER EXECUTION.

AUTHORIZATION SHALL NOT,
BY ITSELF,
PROVE EXECUTION.

EXECUTION SHALL REVALIDATE
CURRENT AUTHORITY,
CURRENT SCOPE,
CURRENT POLICY,
AND CURRENT REVOCATION STATE.

DRAFT COMPLETENESS SHALL NOT,
BY ITSELF,
CONSTITUTE CANONICAL ADOPTION.
```

## 25. Current applicability

This RFC establishes no identity, authority request, approval, grant, or
effective authority for any person or account. Existing provisional dossier
records remain provisional unless IIP-1 has separately completed and recorded
its issuance gates. No authority state may be inferred from an account,
administrative identifier, draft document, or test result.

## 26. Open adoption gates

Before AAP-1 can be considered for canonical adoption, reviewers MUST resolve
and record:

1. **Canonical alignment:** consistency with ACCOUNT-1, IIP-1, Big Bang,
   Proof Machine, and WISDOM.
2. **Bootstrap authority:** the constitutional mechanism and evidence for
   authorizing the initial grant issuer.
3. **Review and lifecycle:** adopted definitions and transition rules for
   suspension, reinstatement, revocation, expiry, and review failure.
4. **Registry model:** record schemas, durability, integrity, access,
   retention, recovery, and consistency.
5. **Acceptance evidence:** passing tests for all criteria in Section 23.
6. **Independent governance and security review:** completed reviews with
   findings resolved and recorded.

Until these gates are closed, the release classification remains:

```text
RFC-AAP-1
Version: 0.9.0-RC1
Status: REVIEW CANDIDATE
Canonical Adoption: PENDING
Production Implementation: NOT IMPLEMENTED
Reference Lifecycle Validator: SYNTHETIC ONLY
Operational Authority Effects: NONE
```

## References

- ACCOUNT-1 — account authentication and status (separate protocol).
- IIP-1 — identity issuance (separate protocol prerequisite).
- Applicable PALACO constitutional, policy, WISDOM, authorization, and
  execution specifications.

The references above name dependencies; this RFC does not assert their
adoption, completeness, or implementation.
