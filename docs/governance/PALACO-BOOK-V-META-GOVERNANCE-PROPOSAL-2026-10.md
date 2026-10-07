# Book V Meta Governance and Registry proposal

Status: `DRAFT_PROPOSAL`  
Classification: `NON-CANONICAL / DESIGN INTAKE`  
Date: 2026-10-07  
Branch: `codex/palaco-book-v-meta-governance-intake-20261007`

## Purpose

The latest proposal recommends a standalone Book V for Meta Governance and Registry Specification. It introduces PMS-001 through PMS-005, PCR-000 through PCR-007 and PSV-001/002, together with a polymorphic registry, relationship graph and validation rules.

This document records the design intake. It does not establish Book V, a canonical registry, authority, a lifecycle transition or a release gate.

## Proposed specification stack

| Layer | Candidate specification | Intended scope |
| --- | --- | --- |
| Meta model | PMS-001 | shared metadata and polymorphic object envelope |
| Relationships | PMS-002 | typed graph edges and relationship evidence |
| Lifecycle | PMS-003 | states, transitions, effective time and replay |
| Classification | PMS-004 | epistemic, criticality and impact dimensions |
| Traceability | PMS-005 | parent, dependency, requirement and evidence links |
| Registry | PCR-000 | registry records, identifiers and source pins |
| Metadata | PCR-001 | required metadata fields |
| Identifiers | PCR-002 | identifier syntax and collision rules |
| Lifecycle standard | PCR-003 | record lifecycle requirements |
| Traceability standard | PCR-004 | reference and lineage requirements |
| Governance standard | PCR-005 | decision and approval references |
| Evidence standard | PCR-006 | evidence and provenance requirements |
| Audit standard | PCR-007 | inspection and findings records |
| Validation | PSV-001 | structural and semantic validation diagnostics |
| Governance rules | PSV-002 | decision, authority and transition constraints |

All entries remain proposals until each receives an inspectable source, decision record, provenance and scoped evidence.

## Candidate object families

The proposal identifies FE, PDP, PCS, GOV, CAP, DOM, OBJ, POL, RSK, REQ, ARC, ADR, INT, DAT, APP, SVC, API, MOD, REP, CFG, COM, VER, TST, EVD, AUD, RUN, MON, EVT, INC and CHG.

The repository stores this inventory in `docs/schemas/draft/pms-001-object-inventory-2026-10.json`. The inventory is descriptive; it does not create registry entries or authority.

## Candidate relationship graph

The proposed relationships are `IMPLEMENTS`, `REALIZES`, `SATISFIES`, `DEPENDS_ON`, `DEFINED_BY`, `CONSTRAINED_BY`, `VERIFIED_BY`, `PROVEN_BY`, `AUDITED_BY`, `OWNS` and `APPROVES`.

Each edge needs a source, target, relation scope, evidence reference, effective time and provenance. `OWNS` identifies a custody or responsibility relation; it does not grant authority. `APPROVES` points to an explicit decision record; it cannot create approval merely because an edge exists. `VERIFIED_BY` and `PROVEN_BY` remain scoped evidence relations.

## Validation limits

JSON Schema can validate local shape, enums, cardinalities and conditional required fields such as ADR or service fields. It cannot by itself prove that:

- a referenced object exists in the same registry snapshot;
- a commit or digest is the intended source;
- a lifecycle transition is adjacent and authorized;
- a graph is acyclic or semantically consistent;
- two sources are independent;
- an approval relation carries valid authority;
- evidence is sufficient for a purpose;
- an object is canonical.

Those checks require a registry-aware validator, transition evaluator and evidence/provenance resolver. They must produce diagnostics and transition records; they must not silently rewrite states or history.

## Required PALACO boundaries

Book V must preserve constitution-bound authority, explicit authorization before execution, append-only Quay history, provenance and uncertainty in Linnaeus/HORTUS, the RIO/ELIXER distinction and the rule that CI/evidence/verification is not runtime authorization. The exact spelling `VORM9EVIN9` is mandatory.

## Safe next step

The next implementation step is a bounded PMS-001 contract review: agree the object envelope, identifier namespace, relation vocabulary, lifecycle state machine and validator responsibilities before generating a large normative schema. No Book V canon, public API or runtime behavior is introduced by this branch.
