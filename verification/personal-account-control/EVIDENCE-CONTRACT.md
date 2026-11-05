# Local verification evidence v0.1

Run from the repository root, with Python 3 and no external packages:

```sh
python verification/personal-account-control/verify.py --output work/account-evidence-new-run
python verification/personal-account-control/verify.py --check work/account-evidence-new-run
```

Choose a new output directory on every run. Existing evidence is never overwritten.
A failed or interrupted run cannot reuse a previous PASS. Process exit code 0 means
the named local checks passed; nonzero means refusal, test failure or incomplete
verification. --check does not rerun tests; it checks the saved package against
current source bytes and the fixed test inventory.

## Package contents

- evidence.json: schema, UTC host timestamps, Python/SQLite versions, Git base
  HEAD (informational), source SHA-256 map, stability result and suite summaries.
- evidence.sha256: SHA-256 of the exact JSON bytes, for accidental-change detection.

Source binding covers every top-level Python/Markdown file in this slice, the
fixed test-inventory.json, and the existing review_gate.py, its tests and its
JSON template. Candidate RIO Rust source files, SQL migrations and Cargo.toml/
Cargo.lock are additionally source-bound; this does not mean those service tests
execute in the Python runner. The runner hashes sources before and after execution. The base
HEAD does not identify uncommitted work: the source hash map binds these bytes.
Timestamps are host-clock observations, not trusted timestamp attestations.

Two suites execute in separate Python subprocesses: accounts (155 tests) and
existing_review_gate (8 tests). The explicit inventory lists their exact test IDs.
Missing, additional or repeated test IDs, errors, failures, skips, expected
failures, unexpected successes, source drift and subprocess timeouts prevent
PASS. Inventory changes require an explicit review of the test additions or
removals; the runner does not silently regenerate it. Each subprocess has a
60-second timeout. Raw output and exception messages are discarded, not attached.

On ordinary failure the report records FAIL; infrastructure failures record
NOT_COMPLETED for the affected suite. Early filesystem/source errors refuse the
run without claiming a complete package. Consumers must require both a passing
report and successful --check for the current source tree.

## Claims intentionally bounded

Every report retains SYNTHETIC_ONLY, production HOLD, account1 HOLD, authority
NONE, humanApproval NOT_VERIFIED and runtimeIntegration NOT_EXECUTED. No generated
session token, password, CSRF value, DB snapshot, environment dump or raw test log
belongs in this artifact. Test IDs, relative source paths and source digests are
public verification metadata.

This is an unsigned local observation. A matching digest is not a signature;
someone able to rewrite the package can rewrite its digest. --check validates
source/inventory/summary consistency, not independent authenticity of execution.
No trusted CI identity, external timestamp, reviewer signature, OIDC/MFA evidence,
historical completeness, production authority or release approval follows.

Fifteen verifier tests cover source drift, incomplete/failing suites, missing or
duplicate tests, authority promotion, duplicate JSON keys, modified artifact bytes,
stale-directory refusal, timeout failure and stable serialization.

AI review: TRIAS — all production gates preserved; no publication or activation.
ORACLE — real local execution is summarized and source-bound, unsigned and
unattested. MENTOR — this closes the reference-slice evidence step; the next
valid action is review of the complete source/report and a proposed synthetic
runtime integration contract, not production release.

The v0.10 boundary also records rioServiceTests NOT_EXECUTED. Standalone Rust
module evidence is separate; full-service dependency resolution is currently blocked.

The existing rio-accounts-synthetic workflow is source-bound as of v0.11.
Its new verification step does not change the report's local-only proof scope;
full-service/real-OIDC results require the subsequent actual CI stages.

As of v0.12, source binding includes the embedded RIO HTML/JS/CSS assets as well
as Rust source. The optional review overlay preserves that exact selected source
map and the passing evidence; it neither signs it nor supplies full-service PASS.

The v0.13 source map additionally binds upstream-parity account readback and
mobile helper/interaction files. Their presence/hash does not assert execution
of Playwright tests. PUBLICATION-PLAN.md distinguishes the older local HEAD
from observed remote main and the unexecuted proposed publication parent.
