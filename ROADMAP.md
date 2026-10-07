# Genesis Roadmap

Architectural scope is locked: consolidate Foundation/Core before adding
subsystems. Existing extensions are retained, not newly authorized.

| Gate | Work package | Acceptance boundary |
| --- | --- | --- |
| A1.1 | Repository Foundation | Canonical root structure, policy entry points and source-bound verification |
| A1.2 | Cargo Workspace | Reproducible dependency resolution and verified Rust build/test/lint |
| A1.3 | Kernel Core | Small, reviewed validate/authorize/execute/evidence contract |
| A1.4 | Runtime Engine | Controlled execution without authority escalation |
| A1.5 | CI | Observed automatic build, test, quality and audit results for the candidate |
| A1.6 | Bootstrap | First runnable PALACO start with attributable evidence |
| A1.7 | Verification | Evidence bundle, ledger and explicit independent review decisions |

This change addresses A1.1 only. Existing Rust contracts and workflows are
inputs for subsequent verification, not proof that subsequent gates passed.
Actual results and blockers belong in
[GEN-A1 verification](docs/evidence/GEN-A1/verification.json).
GEN-A2 and autonomous evolution remain out of scope until GEN-A1 is certified.
