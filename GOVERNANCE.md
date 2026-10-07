# PALACO Governance

> Governance may constrain execution; execution may never silently redefine governance.

The [constitution seed](docs/constitution/constitution.md) states the GEN-A1
invariant alongside the preserved [constitutional source](docs/constitution/PCS/Constitution.md).
Execution-facing components enforce boundaries; they do not own constitutional
amendment authority. Runtime, Living Kernel, Evolution/WAE and future agents
must not autonomously widen their authority.

## TRIAS responsibilities

- **Architect:** delimit scope and review architectural/constitutional changes.
- **Builder:** implement within the approved boundary and supply source evidence.
- **Validator:** independently check commands, results and their source binding.

These are responsibilities, not claims that reviews already happened.
Oracle evidence verification and Mentor maintainability acceptance require
explicit review records; labels cannot replace evidence.

## Changes and certification

Constitutional changes require an explicit proposal, review by repository
maintainers, an authorization record and verification before execution uses
the changed boundary. A runtime result or evolution proposal is not approval.
This foundation does not implement an amendment service or authority registry.

Every gate must retain this chain:

```text
source → compile → test → lint → audit → evidence → ledger
```

A command success establishes only what that command checks. Failed, skipped,
unavailable and unreviewed checks remain visible. No overall GEN-A1 PASS,
TRIAS certification, Oracle verification or Mentor acceptance may be inferred
from scaffolding or earlier release evidence. See [RELEASE.md](RELEASE.md).
