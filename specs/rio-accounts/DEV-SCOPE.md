# T01/T02/T03 — Synthetic RIO account development scope

Status: ENGINEERING CANDIDATE / SYNTHETIC_ONLY. ACCOUNT-1, integration and production stay HOLD.

The user authorized further construction on 13 October 2026. This records implementation choices for a disposable development slice, not architecture acceptance, provider procurement, account enrollment, independent review or production authorization.

## Bound starting points and isolation

- Account architecture: Notion page38187de283774f6fa973b0f53be4298e v0.1, edited2026-10-10T13:19:33.470Z, sections11/16–18. Private taskplan3f729e9a126a81c683c7d2279b19d257 supplies T01–T08 and open decisions.
- Base: PALACO main `deb9f80e8c40c03f08021b044a9c31a03c4935ec`.
- Separate candidate: `feature/rio-accounts-synthetic-dev`. This slice does not import the unmerged runtime branch `27f00fa5695ef3871953d35e21f370d4e0bf358b` or modify the root workspace, Citadelwebsite or its closed account routes. The existing runtime is27commits ahead of the base; comparison lists300paths and is not a full audit of that branch.
- Isolated Rust package under services/rio-accounts; [workspace] boundary avoids unreviewed kernel dependencies. No deployment manifests, real candidate codes/addresses, issuer keys or invitation actions are included.

## Local development decisions

Keycloak26.8.0 is selected only for the disposable testfixture, based on the [official release](https://www.keycloak.org/2026/10/keycloak-2680-released). The image manifest digest is captured and pinned by the initial verification. No production operator, region, contracts, mail domain or paid service is selected.

The BFF binds127.0.0.1:8088 but has origin **https://localhost:8088** and exact callback /auth/callback. It uses a fresh one-day loopback certificate. The fixture IdP is **http://127.0.0.1:8089/realms/rio-synthetic**; HTTP is an explicit loopback-only development exception, not a production transport mode. Separate hostnames avoid the same-host/cookie-port ambiguity. Browser certificate exceptions apply only to this disposable local test; the application does not globally disable TLS verification.

The client is confidential rio-bff, authorization-code only with S256 PKCE and openid-only scope. Registration, password grants, service accounts, email login, email recovery and SMTP are disabled. The only admitted subjects are explicitly fictitious TST-alpha and TST-beta. They are not the real first candidates or a pioneer register.

The fixture creates random runtime passwords, a random confidential-client secret, a temporary TLSkey and a distinct Compose project in ignored private .runtime files. No runtime values belong in Git, reports, screenshots, request traces or logs.

The BFF uses maintained [openidconnect4.0.1](https://docs.rs/openidconnect/4.0.1/openidconnect/) with exact direct dependencies and a committed Cargo.lock. Browser verification uses Playwright1.64.0 and a committed npm lockfile. Tested compiler/runtime versions are reported by CI rather than assumed from a tag.

## Implemented T02 boundary

- Guard discovery/JWKS/token URLs and methods before network I/O; no proxy, redirects or arbitrary issuer/client/callback hints. Bound transport time and responsebytes.
- Browser-bound, opaque one-use login transaction; state, nonce, PKCE, strict callbackschema and exact issuer/audience/authorizedparty/signingalgorithm.
- Actual library signature validation and access-token hash check when supplied; no retained provider tokens or email-derived subject linking.
- Opaque __Host-rio_session and __Host-rio_transaction cookies: Secure/HttpOnly/SameSite=Lax/Path=/ with no Domain. Only hashes identify server-side memory records.
- Bounded temporary maps, sessionrotation, expiry and exact Host/Origin/CSRF checks for POST logout/logout-all. Clearing one actor cannot revoke another actor's sessions.
- Client code stores no login tokens; it reads only its own synthetic account and holds the CSRF value in page memory.
- All status/me responses remain SYNTHETIC_ONLY, accountActive=false, operativeAuthority=NONE, canOpenContact=false and ACCOUNT-1 HOLD. Local logout does not pretend to end the separate IdP session.

Session limits in this disposable fixture are idle30seconds and absolute60seconds; transactions expire after300seconds. These are development settings, not accepted production assurance policy. T02 used process memory. T03 replaces the session runtime with a separate local PostgreSQL fixture and adds bounded synthetic records, purpose-bound consent, actor-specific revocation and recovery fencing. Unfinished login nonce/PKCE material still closes on restart. See [the T03 storage contract](T03-STORAGE.md) for the exact durability/restore boundary and required evidence. Recovery/mail, independent security/privacy/operations review and real invitations remain later tasks.

## Evidence and unfinished work

CI must build the actual Rust binary, verify its unit/router and real-signature negative tests, then start the real Keycloak container and exercise two isolated browsers. A browser fixture is not an independent security acceptance. Summaries contain only public package/digest metadata, fixed case IDs and numeric source lines, not raw credential diagnostics.

No assertion of full Rust/Node bridgeconformance, trusted safety issuer, officialidentity, 5CRIPTIE issuance, pioneer-admission, live NOVA contact, E2EE, production readiness or release follows from this slice. The historical CodeQL/review gaps and all relevant later taskplan decisions remain open.
