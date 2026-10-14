# T05 — Closed account-staging plan preflight

Status: PLAN_ONLY / SYNTHETIC_ONLY. Account staging is not provisioned or enabled.
ACCOUNT-1, personal accounts, contact, human acceptance and deployment remain HOLD.

## Purpose and current source boundary

The offline checker makes the next account-hosting proposal testable before a
runtime configuration is built. It checks exact HTTPS names, callback/provider
binding, image-pin syntax and closed policy fields. It performs no DNS, HTTP or
other application network probes, generates no secrets, connects no provider,
deploys nothing and issues no account.

The source baseline is PALACO
[main@facf4f2c5bd0898da1dcf80bb80ec861aa70e062](https://github.com/Maurits-pixe/PALACO/commit/facf4f2c5bd0898da1dcf80bb80ec861aa70e062).
This isolated change does not include, modify or merge the later
[PR #54 mobile diagnosis and VORM9EVIN9 guidance](https://github.com/Maurits-pixe/PALACO/pull/54).
Its success is separate from that PR's exact-head login results.

The existing program cannot consume this plan. Its
[listener](https://github.com/Maurits-pixe/PALACO/blob/facf4f2c5bd0898da1dcf80bb80ec861aa70e062/services/rio-accounts/src/main.rs),
[origin/provider guards](https://github.com/Maurits-pixe/PALACO/blob/facf4f2c5bd0898da1dcf80bb80ec861aa70e062/services/rio-accounts/src/lib.rs),
[storage transport](https://github.com/Maurits-pixe/PALACO/blob/facf4f2c5bd0898da1dcf80bb80ec861aa70e062/services/rio-accounts/src/storage.rs)
and schema are fixed for the loopback-only synthetic fixture. Keycloak uses a
disposable development realm. An environment variable or deployment manifest
does not turn these boundaries into public staging. A separate reviewed runtime
adapter, database-TLS path and persistent IdP setup are still required.

## Running the actual offline program

Python 3.11 or later; standard library only, no installation or cloud account:

~~~sh
python -m unittest discover -s verification/rio-staging-plan -p test_staging_preflight.py
python verification/rio-staging-plan/staging_preflight.py verification/rio-staging-plan/t05-staging-plan-template.json
~~~

The committed template intentionally contains nine null configuration slots:
seven endpoints and two image pins. It must return INCOMPLETE with exit code 2.
These are open decisions, not guessed service URLs or authorized production pins.
Use a private local copy for a proposed configuration. It must contain no
password, client secret, token, database URL, key, candidate email or other
personal data. The checker never writes an output file or displays input values
or the filename. Do not commit an operator's private configuration.

| Result | Exit | Meaning |
| --- | --- | --- |
| CONFIGURATION_CONSISTENT | 0 | All declared fields meet this proposal's strict shape and mutual binding |
| INCOMPLETE | 2 | Schema/policy is valid, but known configuration slots are null |
| REJECTED | 3 | Invalid input, policy, URL, binding, source reference or pin syntax |

All three results have launchSupported=false, deployAllowed=false,
account1=HOLD, humanAcceptance=HOLD, personalAccounts=false,
publicRegistration=false, contact=false, operativeAuthority=NONE
and deployment=HOLD. Exit 0 is never launch or account authorization.

## Input and endpoint contract

The exact RIO_STAGING_PLAN_V1 schema is illustrated by the template.
Unknown or missing keys, duplicate keys at any depth, non-finite numbers,
type-coerced booleans and unsupported modes are rejected. Read at most 16 KiB of
strict UTF-8 from a regular file. UNC/extended-UNC paths are rejected before file
access. Known symlinks are refused; platforms supporting O_NOFOLLOW also prevent
a symlink substitution at open. This does not certify Windows ACLs, parent
directories or mounted-filesystem locality. The operator must select a local
private file; networkProbesPerformed=false describes application probes.

Every present endpoint is checked even when another endpoint is null.
Names use canonical lowercase ASCII DNS spelling and HTTPS's default port.
Explicit ports, IP literals, localhost/local suffixes, wildcards, credentials,
query strings, fragments, controls, whitespace, percent escapes and backslashes
are rejected. Origin has no path or trailing slash. BFF and IdP must have distinct
hostnames to avoid cookie sharing across ports. A domain name passing this
syntax check can still route privately or incorrectly; DNS is unverified.

| Field | Exact path after its HTTPS hostname |
| --- | --- |
| bffOrigin | empty |
| idpIssuer | /realms/rio-synthetic-staging |
| callbackUrl | /auth/callback, on the BFF hostname |
| discoveryUrl | /realms/rio-synthetic-staging/.well-known/openid-configuration |
| authorizationUrl | /realms/rio-synthetic-staging/protocol/openid-connect/auth |
| tokenUrl | /realms/rio-synthetic-staging/protocol/openid-connect/token |
| jwksUrl | /realms/rio-synthetic-staging/protocol/openid-connect/certs |

All four provider endpoint hostnames must equal the issuer hostname.
The declared future staging client is confidential rio-bff-staging,
authorization-code/S256/openid-only. Registration, password grants, service
accounts and SMTP stay disabled; the proposal admits only TST-alpha and TST-beta.
TLS policies are requirements, not observed certificate proofs. Proxy forwarding
remains rejected pending a separate reviewed adapter.

Image fields require version-and-SHA256 syntax for Keycloak and PostgreSQL.
A syntactically pinned digest may be nonexistent or refer to an unsuitable image.
The checker does not contact registries, compare bytes, validate support status
or accept a version for operation. The 40-hex source reference is equally
unverified offline; CI verifies only the checkout used for its own tests.

## Required later engineering and operating work

1. Bind a separately reviewed runtime to the agreed staging origin, exact
   discovery/issuer/client/callback and provider allowlist. Preserve PKCE,
   nonce, state, cookie, CSRF, own-account and current-revocation checks.
2. Establish trusted browser/provider TLS, reviewed reverse-proxy handling,
   managed database TLS, migrations and persistent IdP storage; provision
   secrets privately through the agreed host. Test restart, health, outage,
   restore fencing and bounded sanitized logs on the actual deployment.
3. Record the actual operator, region, cost responsibility, administrator,
   data-processing terms, mail domain, retention, account conditions and
   minor/guardian route. The program does not validate these human decisions.
4. Complete independent security/privacy/operations and physical-device/
   accessibility review. Keep [Issue #50](https://github.com/Maurits-pixe/PALACO/issues/50)
   separate from [the unknown historical login cause #51](https://github.com/Maurits-pixe/PALACO/issues/51).
5. Authorize a specific invitation/activation pilot and bind issuance,
   subject, signer/register, scope, expiry and revocation before any personal
   enrollment. Account login cannot create that authority.

No hosting purchase, provider enrollment, email, real invitation, credential
issuance, personal account or NOVA contact follows from this preparation.

## Evidence method

The user-provided RFMC-II-5CRIPTIE-015 principle CLAIM <= EVIDENCE applies.
A test outcome observes proposal rejection/acceptance under known inputs.
It does not establish DNS, TLS, provider availability, current registry digests,
runtime compatibility, independent human acceptance or reliable personal login.
The summary explicitly sets all such checks to false/unverified and preserves
HOLD regardless of caller-supplied declarations. Tests use reserved
example.invalid names and synthetic pin strings. Historical login failures
remain in issue #51; this checker is not a causal fix.

CI reports exact candidate source, fixed test names/counts and sanitized outcome
categories. No private config values, paths or raw exception messages belong
in public evidence. The incomplete template and a syntactically consistent
synthetic proposal are both required cases; deliberate unsafe proposals must
be rejected, including a malformed sibling hidden beside a null slot.
