# Restart fence and recovery procedure v0.1 — synthetic proposal

Implementation: restart.py. Tests: test_restart.py. Production/ACCOUNT-1 HOLD.
All actor roles are trusted fixture configuration, not verified human identities.
This does not select or authorize real production reviewers or activators.

## Per-start deny rule

RestartGuard wraps GuardedModel. Every newly constructed instance has a fresh
random boot ID, a PID binding and no serving approval, irrespective of persisted
OPEN state. Reading account access, review and activation through this facade
requires a fresh, short-lived boot review and separate fixture approval.
Protective suspension is permitted while grants remain fenced.

PID change and test-clock rollback permanently invalidate that instance. A boot
review and approval are never restored from storage or inferred from an earlier
run's audit events. The local caller supplies a trusted clock; client JSON never
chooses it. A valid serving lease expires with the review, at most 30 test seconds.

## Review and approval gates

Fixture review_boot and approve_boot roles must belong to distinct actors. No
role is seeded automatically. Their mapping is immutable for the fence instance;
this is not a production mandate registry or live role-revocation service.

Review requires writable safety and primary transactions, acquired in that order,
SQLite quick_check success, an OPEN circuit, no pending suspension audit, and
primary SUSPENDED status for every independent deny intent. A SHA-256 digest
binds the current primary and safety rows to a BootReview record containing boot
ID, PID, reviewer, issue time and expiry. The digest is a computed snapshot
identifier, not a signature or proof that recovered snapshots are historically
complete. Review evidence remains in memory; safety incidents record boot ID,
actor and time for review and approval. Full durable review-package archival is
not implemented.

Approval reruns health/reconciliation checks and compares the digest under both
write locks. A changed policy, account, mandate, audit, deny intent or incident
invalidates the pending review. Only that fence's current pending record can be
approved. Successful approval appends an incident before releasing that instance.
Audit/storage failure never releases it. Approval changes no accounts or locks.

Serving still consults GuardedModel for each request. Snapshot comparison is an
approval-time check; it is not continuously recomputed after legitimate serving
mutations. The short lease does not waive underlying model or safety gates.

## Concrete local recovery sequence

1. Start a fresh RestartGuard with serving fenced. Preserve original evidence;
   do not delete a deny intent, rewrite incidents or recreate stores to unlock.
2. Inspect current safety circuit, immutable deny intents, account state and
   pending audit records through trusted local fixture tooling.
3. If OPEN with unreconciled independent intents, a separately authorized
   synthetic support actor calls Model.suspend for each affected account. If
   audit is unavailable, retain AUDIT_PENDING and keep serving fenced. Retry
   deliver_suspension only after storage recovery; it cannot restore access.
4. If the circuit is LOCKED, stop: this implementation has no authorized global
   unlock route. Independent incident investigation and a future governed
   recovery contract are required. A boot reviewer cannot override that lock.
5. For reconciled OPEN stores, the fixture reviewer issues review_boot. The
   separate fixture approver checks the exact pending record with approve_boot
   before expiry. Real deployment additionally requires externally authenticated
   authority and evidence of backup/restore completeness; the fixture does not
   establish those facts.
6. Serve only through RestartGuard; never route around it through Model or
   GuardedModel. At lease expiry or process restart, a new review is required.

## Evidence limits

Nineteen new tests include separate-process startup, stale OPEN snapshots restored
over both files, review tampering, other-boot replay, role separation, expiry,
policy/incident changes, reconciliation, approval audit failure, PID and clock
changes, protective suspension and preservation of existing account/global locks.

The restored-snapshot test proves refusal before a new boot approval. It does
not recover lost deny history: a reviewer with only stale stores cannot establish
history completeness, and the synthetic health checks cannot discover that loss.
No external witness, immutable backup ledger, real MFA, human attestation,
power-loss resilience, multi-host coordination or runtime deployment is claimed.

AI review: TRIAS — no reset or production authority; separate review boundaries.
ORACLE — local synthetic tests only; historical completeness remains UNVERIFIED.
MENTOR — next step is a concrete evidence package and reproducible verification
entry point for the complete slice, before proposing runtime integration.
