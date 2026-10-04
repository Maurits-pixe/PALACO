# ∆ GO-025 — L.A. IMPLEMENTATION PLACEMENT & MERGE GATE

Status: ENGINEERING / PLACEMENT GATE

Repository: `Maurits-pixe/PALACO`
Branch: `go-025-la-implementation-placement`

## 1. Purpose

GO-025 converts the GO-024 repository reconciliation into a controlled implementation-placement decision.

The repository is authoritative for what is actually implemented. PALACO specifications remain authoritative for intended constitutional behavior. No specification is treated as source code until the repository contains and validates the corresponding implementation.

## 2. Observed repository state

The current PALACO repository contains historical and canonical material, including `README.md`, `Structure`, `MANUAL REPOSITORY ASSEMBLY`, and `MBvanGeen/palaco-foundation`. The repository does not currently establish the previously designed `crates/palaco-la/` implementation as existing source.

The PALACO-Citadel repository contains the PALACO-GITHUB-001 Foundation Repository Assembly Manifest and a broader Citadel-oriented architecture/documentation surface. The manifest defines the intended Foundation workspace progression and explicitly separates constitutional authority from GitHub infrastructure.

## 3. Placement decision

The L.A. implementation SHALL be introduced as a controlled PALACO subsystem, not by rewriting historical repository material and not by replacing existing Citadel identity/provenance components.

Target implementation boundary:

`PALACO`
→ `crates/palaco-la/`
→ L.A. domain/application/verification/authorization/revocation/persistence/API layers
→ PostgreSQL `la` schema
→ PVB-011 cryptographic boundary
→ Citadel identity/provenance boundary
→ PROMA verification/proof surface
→ VORM9EVIN9 presentation
→ RIO interaction layer

## 4. Merge gate

No implementation merge to `main` is authorized merely because source files compile.

Required sequence:

1. Repository placement verified.
2. Existing implementation conflicts checked.
3. L.A. domain boundaries verified.
4. PVB-011 exact-canonical-signature contract verified.
5. `ACCESS ≠ AUTHORIZATION` invariant verified.
6. `DECISION ≠ EXECUTION` invariant verified.
7. `SIGNATURE ≠ AUTHORITY` invariant verified.
8. `PROVENANCE ≠ PERMISSION` invariant verified.
9. Revocation and expiration gates verified.
10. RIO authority-boundary tests verified.
11. Rust architecture checks verified.
12. PostgreSQL migration/reconstruction tests verified.
13. PVS-001 and PVS-002 evidence produced.
14. Evidence manifest updated.
15. Only then may a merge/release gate be considered.

## 5. Initial implementation boundary

The first source slice SHALL be deliberately narrow:

- typed L.A. identifiers;
- event envelope;
- canonical serialization;
- SHA-256 digest;
- signature verification boundary;
- append-only event-store port;
- decision/authorization/execution separation;
- architecture tests preventing authority leakage.

PostgreSQL persistence and the complete HTTP surface follow only after this boundary passes its verification gate.

## 6. Forbidden shortcuts

- No blind overwrite of existing PALACO files.
- No duplicate identity engine where Citadel already owns identity.
- No duplicate provenance engine where the existing provenance contract is canonical.
- No authority inferred from intelligence.
- No authority inferred from cryptographic validity.
- No execution from a decision alone.
- No retroactive history mutation.
- No direct RIO authority mutation.

## 7. Constitutional invariant

> L.A. SHALL NEVER DERIVE AUTHORITY FROM INTELLIGENCE.

Intelligence may analyze, correlate, summarize, detect, explain, or recommend. Authority remains governed by the constitutional chain:

`CONSTITUTION → AUTHORITY → AUTHORIZATION → EXECUTION`

## 8. GO-025 gate state

**PLACEMENT: ESTABLISHED**

**SOURCE IMPLEMENTATION: NOT YET CLAIMED**

**MERGE: BLOCKED UNTIL VERIFICATION EVIDENCE EXISTS**

**NEXT: GO-026 — FIRST L.A. SOURCE SLICE + ARCHITECTURE TEST GATE**
