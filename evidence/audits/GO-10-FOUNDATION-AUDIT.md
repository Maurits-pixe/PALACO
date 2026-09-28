# GO-10 — Foundation Audit

**Baseline:** PALACO Foundation Edition v1.0.0  
**Repository:** `Maurits-pixe/PALACO`  
**Gate:** GO-10 — Audit  
**Audit model:** evidence-preserving, fail-closed, release-blocker aware

## Scope

GO-10 audits the assembled Foundation repository after GO-09. It verifies:

- canonical import provenance;
- workspace and cross-crate integrity;
- build, test, formatting and clippy regression;
- PVS-001 and PVS-002;
- GO-09 Evidence Seal verification;
- GitHub Actions permissions and immutable action pinning;
- ratified licensing state;
- publication safety;
- release-blocker visibility.

GO-10 does **not** claim deployment, production runtime conformance, external certification, or release deployment readiness.

## Evidence basis

The GO-09 seal remains historical evidence for the validated Foundation subject state:

- subject commit: `e0049d81291bc3035c6e6a45e7ef585bb727452b`
- subject tree: `e02b4b0186b5d5ba77ad1ef1be282e35ebd296a4`
- GO-04 through GO-08: completed / success on that subject commit
- GO-09 seal verification: completed / success
- sealed subject GitHub signature state: `unsigned` (preserved, not upgraded)

GO-10 subsequently hardened CI supply-chain references and set crate publication fail-closed.

## GO-10R licensing resolution

The owner ratified **Option A — `MIT OR Apache-2.0`**.

Current required state:

- root Cargo expression: `MIT OR Apache-2.0`;
- root `LICENSE`: dual-license choice declaration;
- `LICENSE-MIT`: MIT License;
- `LICENSE-APACHE`: Apache License, Version 2.0;
- all seven Foundation crates inherit the workspace license;
- `publish = false` remains enabled as a separate distribution safety gate.

This closes the former licensing blockers:

- `AUD-REL-001 — Canonical license not approved` → **CLOSED BY GO-10R RATIFICATION**
- `AUD-REL-002 — License declaration/file mismatch` → **CLOSED BY GO-10R RATIFICATION**

## Audit controls

| Control | Required state |
| --- | --- |
| GO-03 substantive canonical artifacts | 28 with direct or bounded extraction provenance |
| PVS-001 | PASS |
| PVS-002 | PASS |
| Formatting / clippy / check | PASS |
| Workspace build | PASS |
| Workspace tests | PASS |
| PVS-002 explicit integration test | PASS |
| GO-09 seal | PASS |
| External GitHub Actions | immutable 40-hex commit SHA |
| Workflow permissions | explicit read-only |
| Rust toolchain | pinned to 1.98.1 |
| License | `MIT OR Apache-2.0`, owner-ratified |
| License files | `LICENSE`, `LICENSE-MIT`, `LICENSE-APACHE` present |
| Crate publication | `publish = false` inherited by all seven crates |

## Audit observation

The GO-09 subject commit is unsigned according to GitHub signature verification. This remains an evidence limitation only; GO-10 does not transform it into a signed artifact.

## Closing rule

GO-10 is complete only when its CI workflow independently re-runs the technical regressions, verifies the Evidence Seal, validates the ratified license state, and passes the machine audit.

When that run reports `release_blockers=NONE`, GO-11 Release Manifest may open. It still does not imply deployment or package publication.
