# T05 — Immutable endpoint adapter in the account kernel

Status: ENGINEERING CANDIDATE / SYNTHETIC_ONLY. ACCOUNT-1, account staging,
personal accounts, independent acceptance, contact and deployment remain HOLD.

## Result and bound dependency

Previously provider, client, callback, token and browser/mutation checks used
separate constant references. The account kernel now shares one immutable
RuntimeEndpoints object between AppState, its guarded HTTP client and middleware.
The production constructor still builds only the original loopback bindings.

This is a stacked continuation of
[PR #54](https://github.com/Maurits-pixe/PALACO/pull/54),
frozen parent 0539d5e2b3b8d8e30d928e6c678bd420c3c7ff8e. It preserves that
candidate's VORM9EVIN9 guidance, bounded failed-login observations and eight-round
durable/mobile probes. The separate offline full-plan preflight in
[PR #55](https://github.com/Maurits-pixe/PALACO/pull/55) is not merged or imported.
Source review, exact-head CI and human acceptance are distinct evidence.

## Real kernel integration

The same immutable endpoint binding now supplies:

- allowlisted discovery/JWKS GET and token POST before provider network I/O;
- discovered issuer/auth/token/JWKS metadata comparisons;
- confidential OIDC client, issuer, authorization/token and callback values;
- browser Host and HTTP/2 scheme/authority comparison;
- optional callback issuer and signed-token audience/authorized-party binding;
- Origin checking for both logout operations and consent writes.

Unique-header validation, proxy/bearer rejection, request/query/body bounds,
RS256 verification, state/nonce/PKCE, one-use login fences, at_hash,
host-only Secure/HttpOnly/Lax cookies, CSRF, actor isolation, session lifetimes,
durable revocation, restore fencing and error redaction are retained.
Missing azp remains allowed only under the existing single-audience contract.
Root ORIGIN/ISSUER/CLIENT_ID constants remain compatible re-exports of the same
loopback values. No new dependency or lockfile change is introduced.

## Planned staging component and type boundary

StagingEndpointPlan is a public, pure planning type with private fields.
Two canonical HTTPS DNS origins derive one fixed staging realm/client and all
seven endpoint fields. The alternative JSON constructor accepts only those
seven fields, with strict string types, duplicate/unknown-field rejection and
a 4096-byte limit. It is an endpoint component, not the full PR #55 plan,
an operator decision, identity proof, runtime configuration or release grant.

Canonical spelling excludes HTTP, userinfo, controls, whitespace, Unicode,
ports (including explicit :443), percent/backslash ambiguities, local suffixes,
IP spellings, wildcard names and path/query/fragment additions. The BFF and IdP
hosts must differ. JSON endpoints must equal the derived issuer, callback,
discovery/auth/token/JWKS values; field presence alone is insufficient.

Plan errors are fixed categories with no submitted values. A summary contains
only constant scope and closed flags. DNS, certificates, provider metadata,
source references and image digests remain unverified. No input values appear
in Debug output because the plan and underlying endpoint set implement no Debug.

There is no release-build conversion from StagingEndpointPlan to RuntimeEndpoints,
no environment selector and no new launcher option. A compile-fail doctest checks
the public type boundary. A cfg(test)-only conversion permits the actual router
and cryptographic checks to be exercised with reserved example.invalid addresses.
Those offline, in-memory tests do not discover a remote provider, attach the
staging issuer to PostgreSQL or bind a staging listener.

## Why actual staging still requires another implementation

The existing listener remains 127.0.0.1:8088 with local TLS files. Database
transport still admits only the original local PostgreSQL URL and its NoTls
development exception. The migration and two fictional subject bindings still
pin the local synthetic issuer. Keycloak remains the disposable local fixture.
Forwarded and X-Forwarded headers remain rejected.

A future public staging service must first provide a reviewed origin/profile
selection path, trusted TLS and reverse-proxy handling, database TLS, persistent
IdP storage, migrations and issuer-bound account records. It must prove those
bindings before connecting a provider or admitting a session. It cannot use the
test-only conversion or silently relabel the existing database.

Operator/region/cost/mail/retention/account/minor terms, independent safety,
privacy/operations/accessibility review and an authorized invitation/activation
protocol remain separate open decisions. Real accounts and contact stay closed.

## Verification required on this exact candidate

New module cases check derivation, URL normalization, metadata/method binding,
cross-profile refusal, strict JSON, fixed error categories, summary privacy and
shared immutable storage. Seven additional kernel tests exercise:

1. provider allowlists under both profiles;
2. actual guarded HTTP rejection before transport;
3. actual Host/HTTP2 router behavior;
4. proxy, duplicate Host and bearer rejection;
5. planned client/callback/S256 redirect and closed status;
6. actual logout/consent Origin/CSRF handling without a staging database;
7. genuine RSA signatures with issuer/client/azp cross-profile refusal.

Existing unit/fixture/redaction/review-validator checks remain required, followed
by the actual local Keycloak browser suite, ordinary durable/mobile stages,
eight bounded durable and eight Android-emulation repetitions, PostgreSQL
storage/consent/backup/restore, source formatting, locked build/docs, Clippy and
sandbox cleanup. No retry/time limit/access-rule relaxation is introduced.

Results must be bound to the final source head before a PASS claim. These checks
are engineering evidence, not physical-phone acceptance or an independent
security review. Historical failures and unknown causality stay recorded in
[Issue #51](https://github.com/Maurits-pixe/PALACO/issues/51);
[human acceptance #50](https://github.com/Maurits-pixe/PALACO/issues/50) remains open.
The user-provided 5CRIPTIE rule CLAIM <= EVIDENCE applies. This endpoint refactor
is not claimed as the cause-specific correction of the historical login fault.
