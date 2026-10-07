# PALACO filtered governance synthesis

**Review status:** working-branch candidate  
**Date:** 2026-10-07  
**Scope:** cross-repository source filtering and constitutional boundaries

This document is an integration index for review. It does not amend the PALACO Constitution, create authority, certify a runtime, or replace any historical record. It records which statements are supported by inspected `main` files and which remain draft, proposed, conflicting, or unverified.

## Evidence and status vocabulary

- **Canonical source:** a governing rule, accepted ADR, or repository entry point present on the inspected `main` branch.
- **Implemented baseline:** code, schema, test, or implementation profile present on `main`. Implementation is evidence about behavior; it is not automatically a constitutional grant.
- **Proposal/draft:** an open PR, candidate, design note, or conversation statement awaiting ratification or execution evidence.
- **Historical/superseded:** retained material that remains traceable but is no longer the current source.
- **Unverified/conflicted:** a claim with no inspectable source in scope, or records that cannot be treated as one state without a scoped determination.

The current inspected heads were:

| Repository | `main` head | Anchor |
|---|---|---|
| PALACO | `96864384022191e7e6f6fd59134defbd3ae41151` | PCS Constitution, ADR-0002, PAS and RIO documentation |
| PALACO-Citadel | `0bee71771efb3863babd3c0298e3b2cc787c2cdb` | layered entry point, QUAY, provenance and RIO transition profile |
| palaco-genesis | `631a2d02da9f3d5ba8e38df873ccb0eaef43c31c` | Rust constitution, evidence, knowledge and runtime contracts |
| PALACO-INDUSTRIE | `c8832d1c1685ac47c5ea244d3881b5a238fc8eaf` | concept-stage product boundary |
| PALACO-BOOK-1 | `96f6cc21e3e864e1f02b5e52535480195383de02` | Veldgids provenance and evidence-aware knowledge rules |

## Filtered baseline

The following statements have direct repository anchors:

1. The Constitution is the first validity anchor. Authority is not independent of it; authority precedes execution; identity and continuity must be proven.
2. `COMMUNICATION != AUTHORITY` and `MESSAGE != ACTION`. A potentially executable request passes through intent, policy/TRIAS, explicit authorization, bounded execution and trace/evidence registration.
3. QUAY links action, origin, context and evidence so later verification and reconstruction remain possible.
4. The Citadel RIO transition profile is an implementation profile with `constitutional_authority_created: false`; it explicitly does not create canon or authority.
5. Genesis classifies historical material as Canon, Specification, Decision, Design, Experiment, Draft, Rejected or Superseded. Its checks reject missing provenance/evidence/authorization and revoked grants.
6. Genesis evidence is current-context dependent. Partial evidence is insufficient for revalidation. A knowledge record is linked to evidence and provenance and defaults to `Draft`.
7. PALACO-BOOK-1 requires provenance for knowledge and marks AI summaries, classifications and hypotheses as derived material. `VERIFIED` is sufficient only for its defined use; it is not universal truth.
8. PALACO-INDUSTRIE describes itself as concept stage. Its many execution-related branches and open PRs are therefore not treated as released authority.

## Protected filters for this review

The user explicitly requires the following boundaries to be preserved while filtering:

- no derived authority;
- no silent state, time or history rewrite;
- exact spelling `VORM9EVIN9`;
- RIO is the river and is not ELIXER;
- the Linnaeus/knowledge layer preserves epistemic uncertainty and provenance;
- QUAY preserves history;
- CI, evidence and verification are not automatic runtime authorization.

These are applied as review constraints. This document does not claim that the inspected repositories independently ratify every item, and it does not silently elevate a conversation statement to canon.

## Non-authorizing knowledge-to-action sequence

```text
observation
  -> evidence
  -> determination
  -> classification
  -> current/epistemic status
  -> provenance
  -> purpose, scope and temporal adequacy
  -> transition record
  -> governance decision
  -> explicit authorization
  -> bounded execution
  -> Quay/history
```

A transition is an event, not a label overwrite. A valid record carries the subject, prior state, new state, trigger, evidence, rationale, effective time and provenance. A trigger requests reassessment; it does not itself determine truth. A new record may supersede a current interpretation while preserving the previous record and its time context.

`Sufficient for one purpose` does not imply `sufficient for another purpose`. A current or verified result does not imply authority. CI success, evidence sealing and a verification result remain limited to their declared gate.

## Source and conflict notes

- PALACO's file named `Canonical Status` is a shell script and is not used here as a status registry.
- PALACO imports some Citadel documents with source-provenance notes. Those imports are not counted as independent corroboration.
- The referenced CRDG conversation proposes HRAEG, KESG, KAG, ETCG, Linnaeus/HORTUS expansions, source-independence rules, conflict/revalidation models and a seven-ambassador/HOOFDKANTOOR model. Without a mainline source or ratification record, they remain proposal or unverified material.
- Open work is not silently merged into this baseline. Examples include PALACO PR #24, #29 and #30; Citadel PR #9; Genesis draft PR #127; the open Industry GO series; and Book PR #7 and #8.

## Cross-references

- [PALACO-Citadel implementation boundaries](https://github.com/Maurits-pixe/PALACO-Citadel/blob/codex/palaco-filtered-governance-20261007/04-GOVERNANCE/PALACO-FILTERED-BOUNDARIES-2026-10.md)
- [Genesis contract boundaries](https://github.com/Maurits-pixe/palaco-genesis/blob/codex/palaco-filtered-governance-20261007/docs/governance/PALACO-FILTERED-GOVERNANCE-2026-10.md)
- [Industrie product boundary](https://github.com/Maurits-pixe/PALACO-INDUSTRIE/blob/codex/palaco-filtered-governance-20261007/docs/governance/PALACO-FILTERED-GOVERNANCE-2026-10.md)
- [Book knowledge boundary](https://github.com/Maurits-pixe/PALACO-BOOK-1/blob/codex/palaco-filtered-governance-20261007/docs/veldgids/51-palaco-governance-boundary-2026-10.md)

**Not merged, not published and not deployed:** this is a review branch document only.
