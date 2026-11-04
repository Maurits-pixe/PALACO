# Synthetic intake contract v0.1 — proposed, not canonized

This is an executable **in-process contract**, not a running HTTP endpoint.
Implementation: `intake.py`. Tests: `test_intake.py`. All sessions are synthetic.
It is not evidence of a real person's identity, MFA or human approval.

## Trusted boundary

`Intake(model, sessions, clock)` receives its model, session store and clock from
trusted local fixture code. Session tokens and CSRF values are independently
random 32-byte hex values. Only token hashes are stored in the session registry;
the returned raw token is a private fixture credential. The fixture seeds session
actor, workspace, expiry and a simulated strong-authentication flag. This flag
is not MFA proof. Session revocation removes the registry entry.

Client data cannot choose actor, authentication strength, environment or time.
Session actor must independently satisfy the model's current database mandates.
The future OIDC adapter must establish issuer/subject, audience, authentication
strength, session expiry and revocation from validated server-side state. It must
never accept fixture `seed()` calls through a network route.

## Request shape

Both routes require POST, exact `Origin: https://localhost:8088`, exact
`Content-Type: application/json`, `X-CSRF-Token`, and one cookie:
`__Host-pac_fixture=<opaque token>`. Duplicate headers (case-insensitive), duplicate
JSON keys (also nested), unknown fields and non-finite constants are rejected.
The contract accepts at most 20 headers, 512 characters per header value and
4096 bytes of UTF-8 JSON. No query strings or alternative routes are accepted.
This restricted cookie grammar supports only the isolated fixture cookie.

| Route | Exact JSON fields |
| --- | --- |
| `/staging/reviews` | account, revision, workspace, scope, policy, valid_until, checklist |
| `/staging/activations` | account, revision, workspace, scope, policy, until, key |

- `account`: TST- followed by 1–48 ASCII letters/digits/hyphens.
- `revision`: positive integer, excluding booleans.
- `workspace`: synthetic; must match the session workspace.
- `scope`: synthetic:read.
- `policy`: 1–64 characters, must equal the current stored policy.
- `valid_until` / `until`: integer, excluding booleans; server-now < value <= server-now + 300.
- `key`: 8–64 ASCII letters/digits/hyphens, activation only.
- `checklist`: exactly purpose, scope, privacy, risk, escalation, recovery,
  clinical_boundary, human_owner, consent_basis; all values exactly true.

Review intake computes SHA-256 over canonicalized request JSON and stores the
reference `EVD-SYNTHETIC-<digest>` with the model review. This identifies the
submitted fixture payload; it is **not** a signature, provenance attestation or
independent validation of checklist claims. The full payload is not archived.

The model compares revision, workspace, scope and policy inside BEGIN IMMEDIATE,
then checks mandate/review gates and writes state plus audit atomically. Review
and activation use separate fixture session actors. Activation is staging-only.
An idempotent replay rechecks current model gates and cannot undo suspension.

## Response and failure contract

Every response includes Cache-Control: no-store, Content-Type: application/json,
mode SYNTHETIC_ONLY and account1 HOLD. Response bodies never echo input, cookies,
CSRF values, SQLite exception messages or internal denial details.

| Status | Meaning |
| --- | --- |
| 200 | Synthetic review or activation recorded |
| 400 | Invalid input/schema/duplicate data |
| 401 | Missing, expired, revoked or simulated weak session |
| 403 | Origin/CSRF refusal or model gate denial |
| 404 / 405 | Unknown route / method refused |
| 413 / 415 | Body limit / content type refused |
| 503 | SQLite failure; transactional writes rolled back |

## Unfulfilled runtime gates

No socket, TLS handshake, browser cookie issuance, real OIDC, clinical data or
production resource is used. Before any runtime wiring, define and verify:

1. Trusted TLS termination, cookie Secure/HttpOnly/SameSite settings, request
   framing, duplicate preservation and limits before buffering network bodies.
2. Real session and MFA validation, including revocation between request intake
   and commit; the in-memory fixture lookup alone does not prove this race safe.
3. Evidence retention, actual reviewer attestation, mandate issuance and denial
   event persistence. A request digest does not prove those properties.
4. Total-storage-outage suspension policy: v0.4 preserves a committed block during
   audit delivery failure using an outbox, but cannot guarantee suspension when
   the block/outbox transaction itself fails. v0.5 adds an opt-in independent
   GuardedModel; see SAFETY-CONTRACT.md for single-host and dual-store limits.
   The adapter exposes no suspension route; pending audit handling and runtime
   guard wiring must be defined before adding one.
5. PostgreSQL/runtime integration, concurrent session behavior and browser tests.

Status: local contract tested; integration NOT EXECUTED; production HOLD.

## v0.9 final-check extension

Intake now supplies a server-only commit_guard; the registry serializes local
revocation against the final session check/COMMIT. RestartGuard composes its own
fresh lease check and Model validates expiry/mandates again. See
COMMIT-CONTRACT.md for exact scope and the remaining distributed/real-time limits.
No new route or actual HTTP listener is added.
