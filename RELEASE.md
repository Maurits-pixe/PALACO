# Release and Certification

No release or full GEN-A1 certification is authorized by repository
consolidation. Preserve the existing license and historical release evidence.

## Candidate requirements

1. Identify the reviewed source commit and toolchain. For reproducibility,
   bind dependency resolution to a reviewed Cargo lockfile and use locked
   verification commands in the workspace gate.
2. Capture real compile, build, test, format, lint and audit outputs, including
   failures, skipped tests and dependency-audit limitations.
3. Bind evidence to source and record it in a ledger. Local logs and CI runs
   are distinct; CI proof must include the candidate commit and run/job URLs.
4. Resolve blockers without weakening governance or unrelated tests.
5. Obtain explicit TRIAS review, Oracle evidence verification and Mentor
   maintainability acceptance with attributable review records.

Repository, Workspace, Kernel, Runtime, CI, Bootstrap, Tests, Governance and
Evidence may each receive PASS only for their demonstrated acceptance
criteria. Mark other states PENDING, BLOCKED or NOT VERIFIED.
Only after all GEN-A1 requirements and reviews are complete may the ledger
state `THE FIRST STONE IS SET` and authorize moving to GEN-A2.

The current foundation record is
[verification.json](docs/evidence/GEN-A1/verification.json), with a
[ledger entry](docs/evidence/GEN-A1/ledger.json). This is not an attestation of
deployment, dependency safety or external certification.
