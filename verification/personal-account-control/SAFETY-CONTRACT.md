# Independent deny guard v0.1 — synthetic proposal

Implementation: safety.py. Verification: test_safety.py. Production HOLD.
This is an isolated executable model, not a deployed safety service.

## Boundary and state

GuardedModel wraps model.allowed, model.review, model.activate and model.suspend.
Every served access and activation must use this facade to obtain this guarantee.
Direct Model calls deliberately remain available to trusted fixture code and
bypass the new guard; no existing RIO HTTP route has been changed.

SafetyStore requires a persistent SQLite file distinct from the primary model
file, including rejection of identical files and hard links. It contains:

- circuit: UNPROVISIONED, OPEN (fixture-serving), or LOCKED (global refusal).
- denied_account: immutable account, initiating actor and original occurrence time.
- incident: append-only synthetic provisioning, deny-intent and storage-failure evidence.

A new/missing store starts UNPROVISIONED and denies access. Only explicit trusted
fixture_provision_once() can open it, exactly once. It cannot unlock a tripped
store. There is no HTTP provisioning, reset, per-account release or reactivation
operation. These would require a separate human-governed recovery contract.

## Storage failure behavior

Every guard operation acquires a writable BEGIN IMMEDIATE transaction in the
safety store; even an access check cannot rely on a cached OPEN value. A primary
SQLite exception trips LOCKED and records a PRIMARY_STORAGE_FAILURE incident
before returning refusal. Error text, tokens and private payloads are not stored.
If safety storage fails, the current guard refuses and latches refusal in memory;
subsequent calls in that guard continue to refuse. Errors never imply authority.

A suspension first checks the fixture actor's current primary mandate through
the guard. It then commits a per-account deny intent to the independent safety
file **before** attempting primary suspension/outbox writes. If that write fails,
the primary state can remain ACTIVE but guarded access and activation are denied.
A crash after intent commit likewise leaves the independent deny intact. Neither
primary recovery nor audit delivery removes this intent. Before intent commit,
a crash does not prove that suspension was accepted; no such guarantee is claimed.

The safety write lock serializes guarded operations across connections. Operations
that complete before the deny intent can succeed; after its commit, guarded access
fails. Releasing/reacquiring the lock around the intent commit permits another
suspension or a global trip, but no guarded grant for the denied account.

## Result semantics and recovery

Successful primary suspension still returns AUDIT_DELIVERED or AUDIT_PENDING.
Primary storage failure raises Denied(PRIMARY_STORAGE_FAILURE_SAFETY_LOCKED);
this means independent refusal, **not** a successful primary lifecycle transition.
Safety failure raises Denied(SAFETY_UNAVAILABLE). allowed() returns false for
these cases. The HTTP-shaped intake maps Denied to its existing generic 403.

Reconciliation may deliver primary suspension audit via trusted fixture code but
must not silently clear the independent block. There is no automatic recovery
worker or operator alert. Incident inspection is local fixture inspection only.

## Proof boundary and remaining runtime gates

The sixteen new local tests cover default denial, explicit provisioning,
independent suspension intent, primary write/read failures, no automatic unlock,
safety read-only/closed/injected-write failures, authority denial, reopen,
replacement-store defaults, file collision, process exit after intent commit,
concurrent replay/suspension and immutable incident evidence.

Two files on one machine are not independent disks, nodes or failure domains.
This does not establish fleet-wide availability or power-loss durability. A
simultaneous failure of both stores can prevent durable incident writes; the
in-memory safety latch alone is not persistent across process loss. No claim
is made that a restarted process can reconstruct an unrecorded incident once
both stores recover with stale OPEN data. Serving runtime must define an external
startup fence/health policy and operational recovery for that case.

No real identity/MFA, genuine mandate registry, PostgreSQL adapter, multi-host
coordination, session revocation or deployed access enforcement is verified.
The next slice should specify restart fencing and recovery authorization, then
bind a guarded adapter to a synthetic runtime only after those gates are tested.

## v0.6 follow-on

RestartGuard now provides an opt-in per-process startup fence; see
RESTART-CONTRACT.md. It prevents automatic serving from restored OPEN state,
but does not prove lost history complete or supply a global unlock route.
