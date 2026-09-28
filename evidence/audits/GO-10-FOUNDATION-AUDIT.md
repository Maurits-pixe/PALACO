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
- publication safety while licensing is unresolved;
- release-blocker visibility.

GO-10 does **not** claim deployment, production runtime conformance, external certification, or release readiness.

## Evidence basis

The GO-09 seal preserves the validated Foundation subject state:

- subject commit: `e0049d81291bc3035c6e6a45e7ef585bb727452b`
- subject tree: `e02b4b0186b5d5ba77ad1ef1be282e35ebd296a4`
- GO-04 through GO-08: completed / success on the same subject commit
- GO-09 seal verification: completed / success
- sealed subject GitHub signature state: `unsigned` (preserved, not upgraded)

GO-10 additionally hardens CI supply-chain references and makes crate publication fail-closed.

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
| Crate publication | `publish = false` inherited by all seven crates |

## Open release blockers

### AUD-REL-001 — Canonical license not approved

The root `LICENSE` remains an assembly placeholder and explicitly states that authoritative license text must be canonically approved before release.

### AUD-REL-002 — License declaration/file mismatch

The Rust workspace currently declares `Apache-2.0`, while the repository does not yet contain the canonically approved Apache-2.0 license text. Other PALACO source material also contains `MIT OR Apache-2.0` declarations, so GO-10 does not infer or manufacture a licensing decision.

**Mitigation:** all seven Foundation crates inherit `publish = false`. Accidental package publication is therefore fail-closed while the license decision remains unresolved.

## Audit observation

The GO-09 subject commit is unsigned according to GitHub signature verification. This is recorded as an evidence limitation; GO-10 does not transform it into a signed artifact.

## Closing rule

GO-10 is complete only when its CI workflow independently re-runs the technical regressions, verifies the Evidence Seal and passes the machine audit.

A successful GO-10 audit may coexist with open release blockers. **GO-11 Release Manifest remains locked while AUD-REL-001 / AUD-REL-002 remain unresolved.**
