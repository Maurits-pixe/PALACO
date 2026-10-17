# T05 — Late recovery failure rolls back the whole clone transaction

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

Parent draft #73 at `684349d2899c90680780372f6314366787d4728e` passed exact-head
GO-13 and full RIO. Its native recovery proof covers prevalidation refusal and
successful recovery. This extension covers failure after recovery has attempted
changes inside its transaction. Production code, schema and dependencies do not
change.

The sixth existing exact TLS case faults only its owned native restored clone.
It saves the recovery generation, compare-and-sets it to PostgreSQL BIGINT maximum
and takes an opaque snapshot of all ten tables. That nonnegative generation is
schema-valid. The exact existing-namespace bootstrap validator must accept it
without mutation, and both copied session markers must still be live. An early
bootstrap refusal therefore cannot substitute for this proof.

The actual public AppState restore constructor must return its fixed unavailable
error without usable state. The current recovery transaction attempts account
epoch changes, session/login-flow deletion and consent reset before its final
generation increment overflows. A bounded raw row-lock query waits for the failed
transaction to finish and releases its own implicit transaction lock before the
snapshot comparison. All ten clone tables must match their faulted snapshot;
sessions remain live and all primary source tables remain unchanged. No row data,
cookies or raw database diagnostics are exported.

The fixture compare-and-sets only the saved original generation back, requires
full equality with the pre-fault clone snapshot and still-live markers, then
continues the original positive first-fence HTTP-cookie proof. The seventh fresh
OIDC proof remains separate. There are still seven selected TLS cases, unchanged
timeouts, lifetimes and native archive/cleanup requirements. Linux integration is
required to establish actual rollback; compilation is not that evidence.

This is a deterministic late SQL failure in the owned synthetic clone. It does
not establish cancellation behavior, discovery-failure behavior or a historical
root cause. Issues #51/#60/#64 remain UNKNOWN and human acceptance #50 remains
HOLD. Physical/manual review, real accounts/invitations, NOVA contact, staging,
off-site backup policy and production activation remain separate.
