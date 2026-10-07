# PALACO next GO proposal register

**Status:** DRAFT / non-canonical / unverified  
**GO:** `palaco-next-go-epistemic-20261007`  
**Date:** 2026-10-07

This register carries the user-directed proposals into the next GO. It is a research and validation backlog, not a constitutional amendment, authority grant, release gate, runtime contract or canonical seal. The proposals originate in the referenced conversation and are treated as untrusted design material until an inspectable repository source, bounded specification and appropriate evidence exist.

## Shared PALACO filters

Every proposal in this register must preserve:

- no derived authority;
- no silent state, time or history rewrite;
- exact spelling `VORM9EVIN9`;
- RIO as the river/communication surface, distinct from ELIXER capability/catalog meaning;
- Linnaeus/HORTUS as an epistemic and taxonomic layer that preserves uncertainty and provenance;
- QUAY as the historical/provenance reconstruction boundary;
- CI, evidence and verification as scoped evidence, never automatic runtime authorization.

The working separation is:

```text
observation
  -> evidence
  -> determination
  -> classification
  -> current epistemic status
  -> provenance and source lineage
  -> evidence sufficiency (KESG)
  -> purpose/consequence adequacy (KAG)
  -> transition record (ETCG)
  -> governance decision
  -> explicit authorization
  -> bounded execution
  -> Quay/history
```

A gate can reject, defer or require review. Passing a gate does not create authority unless an existing constitutional source explicitly says so.

## Proposal register

| Proposal | Current status | Candidate responsibility | Minimum evidence before ratification |
|---|---|---|---|
| ETCG — Epistemic Transition & Change Gate | Conversation proposal; no exact mainline match found in the inspected code search | define append-only epistemic state transitions | transition schema, allowed-edge policy, temporal/context checks, replay fixture and Quay record |
| KESG — Knowledge Evidence Sufficiency Gate | Conversation proposal; not a mainline contract | assess whether evidence is sufficient for a declared claim/context | evidence bundle rules, provenance completeness, contradiction handling and negative fixtures |
| KAG — Knowledge Adequacy Gate | Conversation proposal; not a mainline contract | assess whether knowledge is adequate for purpose, scope, consequence and time | purpose/consequence vector, critical-dimension veto, revalidation triggers and decision fixtures |
| HRAEG — Hologram Recognition & Authorization/Grant Evaluation Gate | Conversation proposal; no mainline authority source | evaluate a proposed recognition/grant request without inventing authority | constitutional authority source, identity proof, consent semantics, temporal bounds, veto semantics, provenance and denial cases |
| Linnaeus/HORTUS extensions | Conversation design family; no mainline Linnaeus/HORTUS contract | maintain identity, determination, classification, relations, snapshots, uncertainty and drift | object/claim identity model, temporal snapshots, conflict fixtures, source lineage and status-fidelity review |
| Source independence/corroboration | Conversation design rule; no mainline independence field found | distinguish independent evidence from copies or derived reports | stable source IDs, lineage graph, independence assessment rules and adversarial copy-chain fixtures |
| Epistemic conflict/revalidation | Conversation design rule; no mainline `EpistemicConflict` type found | preserve incompatible assertions and trigger scoped revalidation | conflict record, conflict types, identity-first handling, resolution reference, append-only history and replay |
| Seven-ambassador / HOOFDKANTOOR model | Conversation governance claim; unverified and constitutionally unanchored in the inspected mainline | possible future governance design only | explicit constitutional source, role/ownership separation, quorum/veto/time semantics, appointment/revocation rules, audit evidence and independent approval |

## Boundary decisions for this GO

### ETCG

ETCG may model a transition event such as `Verified -> Disputed`, but only when a valid trigger and basis are recorded. A trigger is not a determination. A contrary opinion is not automatically contradictory evidence. The old state remains historical and addressable.

A candidate record may contain:

```text
transition_id
subject
previous_state
new_state
trigger
evidence_refs
rationale
effective_at
provenance_ref
```

This is a draft shape only. It is not added to the Genesis public API in this GO.

### KESG and KAG

KESG and KAG are related but distinct candidates:

- KESG asks whether the evidence and provenance are sufficient for the claim in its declared context.
- KAG asks whether the resulting knowledge is adequate for the intended purpose, scope, consequence and temporal context.

Neither answers “may execute?” and neither replaces governance or authorization. Missing critical dimensions must remain visible; they may not be averaged away. `Verified` and `Sufficient` remain use-scoped, and `Stale` does not mean `False`.

### Linnaeus/HORTUS

The conversation material proposes a living taxonomic model with identity, determination, classification, relation, lineage, temporal snapshots, conflict and drift. The safe boundary is:

```text
classification describes what it is
capability describes what it can do
governance decides what may be done
authorization permits a bounded action
```

HORTUS may observe and surface drift; it does not become reality, Quay, governance or authority. Human-facing `VORM9EVIN9` must preserve status fidelity and must not compress “identified”, “classified”, “verified”, “approved” and “authorized” into one label.

### Source independence

Repeated copies are not independent corroboration. The next specification must model source lineage and independence as evidence metadata, not infer independence from count, domain or repetition. `Unknown` must remain representable.

### Conflict and revalidation

Conflicting claims remain preserved. An identity conflict is a high-impact conflict that blocks unsafe classification until identity determination exists; it does not authorize deletion of either claim. Revalidation creates a new assessment and history record. It does not delete the stale or superseded record.

### HRAEG and seven ambassadors

The conversation describes a staged 5/7 and 7/7 consent path, absolute veto, bounded hologram grant and a HOOFDKANTOOR/Raad relationship. None of those details are treated as existing PALACO authority in this register. Before any implementation, the next GO must locate or obtain the constitutional source that grants such power and define how identity, scope, time, veto, appointment, revocation and evidence are independently proven. A council cannot vote itself into authority.

## Validation sequence for the next review

1. Map each proposal to an existing mainline source or mark it explicitly as absent.
2. Define the smallest non-authorizing record and state model.
3. Add negative fixtures for missing provenance, stale context, copied sources, identity conflict, veto, timeout and missing consent.
4. Check append-only replay and Quay reconstruction.
5. Review wording for RIO/ELIXER separation and exact `VORM9EVIN9` spelling.
6. Only after the above, propose a bounded implementation contract or a constitutional decision record.

**Current result:** all eight entries remain DRAFT / non-canonical / unverified. No runtime code, public API, authority source or release status is changed by this register.
