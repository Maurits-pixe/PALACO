# ∆ GO-19B — Repository Forensic Classification Matrix

Status: FORENSIC CLASSIFICATION — NON-DESTRUCTIVE
Repository: Maurits-pixe/PALACO
Baseline branch: main
Working branch: go-18/write-authorization-proof

## Constitutional boundary

CLASSIFICATION ≠ CANONICAL ASCENSION
PRESERVE ≠ ENDORSE
PRESENT IN REPOSITORY ≠ CURRENT AUTHORITY
CI CONFIGURATION ≠ EXECUTION EVIDENCE

No existing path is moved, renamed, deleted, or rewritten by this inventory.

## Classification vocabulary

- ACTIVE — structured implementation or operational project material currently positioned as executable/buildable repository content.
- GOVERNANCE-EVIDENCE — verification, workflow, policy, provenance, release, audit, or conformance material.
- HISTORICAL-PRESERVE — legacy/large/root-level material retained intact pending provenance and semantic review.
- REVIEW-REQUIRED — ambiguous, unusually named, duplicate-looking, bundled, or otherwise unsuitable for automatic canonical promotion.

## Matrix

| Repository area | Classification | Forensic disposition |
| --- | --- | --- |
| `crates/` | ACTIVE | Preserve; inspect crate contracts and dependency graph before consolidation. |
| `modules/` | ACTIVE | Preserve; inspect launcher/runtime generations independently. |
| `website/` | ACTIVE | Preserve; public gateway/studio implementation requires its own validation boundary. |
| `release-registry/` | GOVERNANCE-EVIDENCE | Preserve; inspect contract, journal, ERA boundary and tests before relying on evidence claims. |
| `.github/workflows/` | GOVERNANCE-EVIDENCE | Preserve; workflow presence alone is not proof of a successful run. |
| `scripts/standards_conformance.py` | GOVERNANCE-EVIDENCE | Preserve; corresponds to standards-conformance gate, but execution evidence remains separate. |
| `tools/` | GOVERNANCE-EVIDENCE | Preserve; contains PVS-001/PVS-002 and release/audit verification tooling. |
| `tests/` | GOVERNANCE-EVIDENCE | Preserve; empty/placeholder suites must not be interpreted as passed validation. |
| `Cargo.toml` | ACTIVE | Preserve as workspace entry point; validate against actual crate tree. |
| `README.md` | REVIEW-REQUIRED | Documentation may mix generations/status claims; compare against implementation and evidence. |
| `PALACO-MONETARY-ARCHITECTURE.md` | REVIEW-REQUIRED | Domain architecture; no automatic constitutional promotion. |
| `PALACO_Foundation_v0.3.0_alpha.zip` | HISTORICAL-PRESERVE | Binary/archive artifact; retain unchanged and provenance-review separately. |
| `333333` | HISTORICAL-PRESERVE | Large root artifact; retain byte-for-byte pending semantic/provenance classification. |
| `Canonical Status` | HISTORICAL-PRESERVE | Large status artifact; name does not itself establish canonical authority. |
| `MBvanGeen/palaco-foundation` | HISTORICAL-PRESERVE | Large historical Foundation artifact; retain pending lineage comparison. |
| `MANUAL REPOSITORY ASSEMBLY` | REVIEW-REQUIRED | Assembly-era record; preserve and inspect before deriving current structure. |
| `Structure` | REVIEW-REQUIRED | Structural note; compare with live tree before use. |
| `ALPHA` | HISTORICAL-PRESERVE | Preserve as historical state marker pending provenance review. |
| unusual root paths / multiline names | REVIEW-REQUIRED | Preserve exactly; do not normalize names without explicit migration plan and evidence. |
| license files | GOVERNANCE-EVIDENCE | Preserve; license consistency requires separate legal/license conformance review. |

## Harvest / consolidation rule

HARVEST
→ CLASSIFY
→ PRESERVE
→ COMPARE
→ CONSOLIDATE CANDIDATE
→ PVS-003
→ PR
→ standards-conformance
→ HUMAN REVIEW

No stage implies the next stage has passed.

## PVS-003 entry conditions

PVS-003 MUST NOT treat repository presence as validity. At minimum it should verify:

1. workspace/tree consistency;
2. duplicate or conflicting source-of-truth candidates;
3. provenance/lineage of material selected for consolidation;
4. active implementation versus historical documentation;
5. workflow/configuration versus actual run evidence;
6. no silent deletion or normalization of preserved material;
7. VORM9EVING spelling and other canonical identifiers remain exact where canonically applicable;
8. proposed canonical assembly is reproducible from an explicitly frozen source envelope.

## Current decision

GO-19B = CLASSIFICATION RECORDED.
No canonical assembly has occurred.
No PVS-003 PASS is claimed.
No merge is authorized.
