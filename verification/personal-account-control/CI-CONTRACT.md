# Existing synthetic CI integration v0.1 — local candidate

Object: reference slice v0.11 and the existing rio-accounts-synthetic workflow.
No workflow has been published, dispatched or observed remotely in this task.

## Concrete change

The existing workflow now includes verification/personal-account-control/** in
both its push and pull-request path filters. Existing branch restrictions remain.
A new step runs the source-bound Python verifier, checks its evidence against the
checkout, and executes the disposable integrated rehearsal before the existing
Rust/service/browser steps. The workflow itself is now part of the verifier's
source SHA-256 map.

The existing Rust stage retains cargo fmt, cargo test --locked, clippy, build and
doc. Later stages retain disposable Keycloak/PostgreSQL startup, actual OIDC and
browser checks, durable-storage and revocation checks, backup/restore and cleanup.
No dependency pin, image digest, permission, secret requirement, service endpoint,
production setting or deployment step is added or weakened.

Failure is not suppressed: the added step has no continue-on-error or always()
condition and the existing Rust step remains mandatory. A successful Python
report still explicitly says rioServiceTests NOT_EXECUTED, because that report's
two suites are Python-only; the subsequent Rust/fixture stages supply their own
CI results. The overall workflow cannot succeed if those stages fail.

## Local validation and blocked evidence

The YAML parses with existing tooling; both event path lists contain the new
slice, the new commands precede the original mandatory Rust stage and the added
shell script passes bash syntax checking. The source-bound local verifier and
integrated rehearsal execute again on this revision.

A fresh full-service test attempt still failed before compilation: axum is not
cached, and index.crates.io cannot be reached through the configured proxy. This
is an environment/dependency-resolution block, not an observed Rust test failure.
There is no new successful service build or remote CI run to report.

## Next valid transition

Local CI candidate → actual synthetic CI execution requires this exact source
candidate to be present in an authorized remote branch/PR and the workflow's
normal branch/path conditions to match. This task does not publish it or dispatch
remote work. Capture the resulting commit SHA, workflow/run/job IDs and logs before
claiming CI PASS. Do not substitute local Python or standalone-module tests.

AI review: TRIAS — production/ACCOUNT-1 HOLD and existing permissions unchanged.
ORACLE — local YAML/shell checks and Python evidence are real; service/remote CI
remain NOT EXECUTED. MENTOR — run this exact candidate through the existing full
synthetic workflow when dependency/network access is available, then review its
results before any stronger-authentication or lifecycle admission implementation.
