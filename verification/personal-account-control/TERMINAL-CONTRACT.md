# Terminal lifecycle v0.1 — synthetic proposal

Object: reference model v0.15, continuing draft PR #106. No live account flow,
production authority, scheduling worker or HTTP endpoint is added.

## Explicit states and fixture authority

REVOKED and EXPIRED are final states. No review, activation, recovery, suspension,
new invitation with the same account ID or transition to the other terminal state
can reopen them. A new account identity and invitation would require a separate
authorized process; the fixture implements no terminal-state reset.

The fixture adds distinct TST-revoker/revoke and TST-expirer/expire roles to its
explicitly seeded synthetic mandates. These proposed test roles are not canonical
human roles and are not issued by OIDC. The role, workspace, scope, mandate expiry
and revocation are checked inside the primary write transaction.

revoke accepts any named nonterminal lifecycle state, including SUSPENDED.
expire accepts only an INVITED account whose invitation deadline has arrived, or
an ACTIVE account whose access deadline has arrived. It refuses staged accounts
without a defined expiry policy and refuses early expiry without creating a deny
intent. Merely advancing time already denies expired access; writing EXPIRED is
an explicit traceable operation. No background expiry scheduler is claimed.

## Durable restriction and evidence

A terminal transition commits state plus an immutable terminal_outbox record
before audit delivery. The record preserves original actor, prior/new state and
time. Delivery writes account.revoked/account.expired plus a receipt atomically.
Retry is idempotent; AUDIT_PENDING never means audit PASS. Payloads cannot be
updated/deleted and delivered receipts cannot be rewritten through ordinary SQL.
Database file owners remain outside the fixture threat boundary.

The safety facade checks authority/deadline before committing a persistent deny
intent, then attempts the primary terminal operation. The existing first deny
intent is retained if the account was already suspended. Protective calls may
operate on already denied accounts, but grant/read calls still cannot. A primary
write failure retains independent refusal and trips the global circuit; it does
not claim the primary state changed. A failed recheck may conservatively leave
the previously committed deny intent; it never restores rights.

RestartGuard permits protective revocation/expiry while serving is fenced. A
new start review requires all suspension and terminal audit records reconciled;
independent deny intents must correspond to SUSPENDED, REVOKED or EXPIRED primary
states. Reconciliation and start approval do not remove those deny intents or
change the terminal state. The snapshot digest includes terminal_outbox rows.

This schema is local SQLite fixture structure, not a production migration.
The new callbacks are trusted local methods and cannot be selected by JSON.

## Executed controls

Eighteen new tests exercise active/staged/suspended revocation; account and
invitation expiry; early/undefined expiry refusal; role and mandate denial;
terminal-state finality; audit outage and reconciliation; idempotence; independent
deny on outbox-write failure; immutable records; identity-reuse/recovery refusal;
process exit after commit; and concurrent activation/revocation ending closed.

AI review: TRIAS — only protective synthetic transitions are added; no admission,
reset, production role or endpoint. ORACLE — local tests cover these named paths;
real organizational roles, expiry policy, worker operations and clinical-data
retention are not decided. MENTOR — rerun the full existing synthetic CI for the
new source head; production/ACCOUNT-1 remain HOLD even if that run passes.
