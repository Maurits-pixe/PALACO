# Consumer accounts and Industrie administration

**Status:** design contract · not implemented for production  
**Pilot limit:** 4,444 pioneer admissions  
**Data in the website preview:** none; static copy only

## Current boundary

`website/#/account` and `website/#/industrie/admin` are non-functional previews.
They have no forms that collect credentials, no identity provider, no backend,
no live pioneer count and no administrative data. Sign-in, account creation,
recovery and invitation actions are disabled. The pages must not be described
as a working login or a live administration console.

The public website is currently a static application with a restrictive
`connect-src 'none'` policy. Do not add client-side password handling,
browser-storage authentication, mock identities presented as real, or an
unreviewed API exception. A production login requires a separately approved
server-side identity and data architecture, deployment configuration, and
security review.

## Independent records and authority boundary

Keep at least these concepts separate:

- **Account:** a service principal that can authenticate.
- **PALACO identity / claims:** separately issued and verifiable records; a
  successful account login is not identity proof.
- **Pioneer admission:** an independently granted, revocable program status
  with a unique place number from 1 through 4,444. The number is not a
  credential, role, Citadel membership or authority.
- **Administrator role:** an individual, scoped, revocable assignment. It is
  never copied into a consumer profile as a trusted client claim.
- **Action authorization:** a fresh policy decision for a particular action,
  target, scope and context. Neither login nor administrator role is sufficient.

Preserve PALACO's rule: **COMMUNICATION ≠ AUTHORITY; MESSAGE ≠ ACTION.** An
administrative request is an intent proposal followed by policy review,
explicit authorization, bounded execution and an attributable receipt.

## Consumer authentication service

The production service must be server-side and use an independently selected
and reviewed identity provider or maintained identity service. Before
implementation, record the provider decision, data residency, processors,
incident contacts, service limits, backup/restore design and exit plan.

The consumer flow must support:

- Passkeys based on a reviewed WebAuthn implementation; accessible,
  privacy-preserving verified-email fallback where passkeys are unavailable.
- Uniform public responses and timing for unknown accounts, incorrect
  credentials and disabled accounts; rate limits, abuse monitoring and
  credential-stuffing defenses without relying on CAPTCHA alone.
- Step-up authentication for credential changes, recovery changes, exports
  and other sensitive account operations.
- Opaque server-managed sessions in `Secure`, `HttpOnly`, appropriately
  `SameSite` cookies; rotate session identifiers after authentication and
  privilege changes; enforce idle and absolute expiry, CSRF protection, and
  per-session and revoke-all logout.
- Account recovery using short-lived, single-use, server-validated recovery
  challenges. Store only protected challenge material, notify established
  contact channels of recovery and security changes, revoke relevant sessions,
  and rate-limit attempts. Support staff must not impersonate a consumer.
- Clear purpose and privacy notices, data minimization, accessible mobile and
  keyboard flows, and documented retention, correction, export and deletion
  procedures.

Authentication confirms control of an account credential only. Any consumer
resource request must independently resolve the server-side account state,
tenant, requested scope, consent, resource ownership and current revocation.

## Pioneer capacity invariant

Admission is closed until the service is reviewed and explicitly opened.
Maintain a server-controlled capacity of 4,444 and distinct admission states,
such as `INVITED`, `PENDING`, `ADMITTED`, `WITHDRAWN`, `REVOKED`. Only
`ADMITTED` consumes a place. Re-admission, transfers and restored places must
be explicit audited policy decisions.

Allocation must be one database transaction that claims a unique slot under
the capacity boundary and writes the admission event. Serialize claims on a
capacity record or use an equivalent database-enforced invariant; never
allocate with a client count or an unprotected `MAX(slot)+1` query. Enforce
`UNIQUE(slot_number)`, `CHECK(slot_number BETWEEN 1 AND 4444)`, and uniqueness
of the active admission per account in the database. Retry serialization
conflicts safely and return a non-enumerating, stable “unavailable” response
when no place remains. Audit and capacity reads must come from the canonical
service.

Test concurrent claims at the final available place and prove that exactly
one transaction succeeds; test the full-capacity case, retries, duplicate
accounts, withdrawal/revocation and recovery without silently reusing a slot.

## Industrie administrator service

Host administration as a separate protected application/service and
authorization boundary. Require individual administrator identities,
passkeys or strong MFA, short sessions, step-up for sensitive operations,
least privilege and monitored break-glass access.

Initial roles are separate server-side grants:

| Role | Bounded scope | Explicit exclusions |
| --- | --- | --- |
| Support | View minimal support state; initiate a documented recovery workflow | No impersonation, credential disclosure, role grants or admission decisions |
| Pioneer operations | Manage invitations and admission states within policy | No identity issuance, security-policy change or external execution |
| Security administrator | Revoke credentials/sessions and contain incidents | No silent use of consumer accounts; high-impact changes require independent approval |

Enforce authorization in the API for every read and write; never rely on a
hidden navigation item, UI check or client-supplied role. Require a reason,
confirmation and target binding for mutations. For role grants, capacity
policy changes, bulk actions and other high-impact operations, require approval
by a different administrator identity. Role assignment and revocation take
effect server-side and invalidate affected sessions/caches.

Append an audit event for authentication/security events and every admin
read or mutation that accesses or changes protected information. Minimize
personal data in audit records: use internal references rather than email or
credential material. Restrict audit read access. The application writer has
insert-only rights; application roles cannot update or delete prior events.
Export audit events to separately controlled retention/backup monitoring.
Each event records actor, effective role, operation, target reference,
decision/reason code, timestamp and correlation ID. Never record passwords,
session cookies, access/recovery tokens, passkey secrets or full sensitive
request bodies.

## Backend and deployment gates

The service requires a reviewed API, persistent database, transactional
admission operation, identity-provider integration, email delivery, secrets
management, monitoring/alerting, backup and tested recovery, incident response,
data retention/deletion processes and operator runbooks. Use TLS, strict
origin/CSRF controls, request validation, security headers and secret rotation.
Review the public site's CSP before enabling only the specific required
identity/API origins. Deployment header inspection is required; repository
configuration alone is not evidence.

Before any real-user pilot:

1. Select and assess the identity provider and hosting/data processors.
2. Complete a privacy impact/data inventory and retention schedule.
3. Threat-model account enumeration, credential stuffing, recovery takeover,
   session theft/fixation, CSRF, tenant isolation, admin escalation, audit
   tampering and concurrent pioneer allocation.
4. Test passkey and fallback, verification, recovery, step-up, session expiry
   and revocation, access denial, admin role boundaries, second-person review,
   atomic last-place allocation, full-capacity behavior and audit reconstruction.
5. Run accessibility review against WCAG 2.2 AA, independent application
   security testing, dependency review and deployment-header checks.
6. Use synthetic data in non-production. Keep registration closed until
   recovery, incident response, backup restoration and independent review pass.
7. Record an explicit release decision. A passing test or completed review does
   not automatically activate registration, issue pioneer status or authorize
   any PALACO action.

The relevant existing PALACO boundary is
[`RIO-AUTH-BOUNDARY-001`](../standards/rio/governance/RIO-AUTH-BOUNDARY-001.md)
and [ADR-0002](../decisions/ADR-0002-communication-not-authority.md).
