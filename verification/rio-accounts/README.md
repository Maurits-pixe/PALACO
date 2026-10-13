# Synthetic RIO account fixture

This is the opt-in local verification environment for the first RIO account slice.
It uses only TST-alpha and TST-beta. ACCOUNT-1, real invitations and production
remain **HOLD**. There is no Render deployment or production identity connection.

## Prerequisites and launch

Use Python 3.11 or later, OpenSSL, Docker Engine 28 or later with Compose v2,
and the repository's
Rust toolchain. From the repository root:

```sh
cargo build --manifest-path services/rio-accounts/Cargo.toml
python verification/rio-accounts/fixture.py prepare
python verification/rio-accounts/fixture.py up
python verification/rio-accounts/fixture.py run-bff
```

The last command runs in the foreground; use a separate terminal for checks.
The BFF is at `https://localhost:8088`, with `GET /healthz`.
The identity provider is at `http://127.0.0.1:8089/realms/rio-synthetic`.

`prepare` generates a one-day self-signed certificate with SAN
`IP:127.0.0.1,DNS:localhost`. Browser automation accepts that local fixture
certificate. The BFF binds 127.0.0.1 but uses the localhost origin, separating its cookies
from the identity provider's 127.0.0.1 hostname. It uses TLS and Secure cookies
with no insecure HTTP cookie fallback. Manual browsers may require accepting this generated local certificate.

`prepare` and `up` reuse an already complete runtime. Stop the BFF, then reset
the container, its dedicated bridge and generated credentials with:

```sh
python verification/rio-accounts/fixture.py down
```

Run `prepare` again for a fresh realm, passwords, client secret and certificate.
The certificate expires after one day. Do not reuse an old runtime after expiry.

## Identity and secret contract

| Item | Fixed fixture value |
| --- | --- |
| Keycloak image | `quay.io/keycloak/keycloak:26.8.0@sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741` |
| Issuer | `http://127.0.0.1:8089/realms/rio-synthetic` |
| Confidential client | `rio-bff` |
| Exact callback | `https://localhost:8088/auth/callback` |
| TST-alpha subject | `11111111-1111-4111-8111-111111111111` |
| TST-beta subject | `22222222-2222-4222-8222-222222222222` |

The client supports Authorization Code with S256 PKCE only. Password grants,
implicit flow, service accounts, device grants and CIBA are disabled.
Its default and optional client scopes are empty; the BFF requests `openid`.
User registration, password reset, email login and email sending are disabled.
The imported profile makes email and names optional. Neither synthetic user
has an email address, a real person's name or a dossier identifier.
The profile intentionally omits `unmanagedAttributePolicy`: the pinned 26.8
runtime represents the disabled policy by absence/null. Its enum does not
accept the UI label `DISABLED` as an import value.

No passwords, private keys or client secrets are committed. Python generates
the confidential client secret as 32 random bytes encoded as 64 hexadecimal
characters; admin and user passwords are independently generated.
The launcher never prints them. Do not print, upload or attach generated runtime
files or environment values as CI artifacts.

The ignored `.runtime/` directory contains:

- `bff.env`: `RIO_DEV_MODE=SYNTHETIC_ONLY`, `RIO_DEV_CLIENT_SECRET`,
  `RIO_DEV_TLS_CERT` and `RIO_DEV_TLS_KEY`; consumed by `run-bff`.
- `test-credentials.json`: private `alpha` and `beta` objects, each with
  `username`, `subject` and a generated `password`; consumed by browser tests.
- `compose.env`: generated administrator password, absolute runtime path
  and unique Compose project name; consumed by the launcher only.
- `rio-synthetic-realm.json`: generated import containing the same client
  secret and synthetic passwords.
- `tls-cert.pem`, `tls-key.pem` and `metadata.json`: local TLS and cleanup state.

On POSIX, the runtime directory is owner-only `0700`, and private files are
`0600`. The realm file is `0644` so Keycloak's container user can read its
single-file read-only bind mount; its host parent remains `0700`.
On Windows, these files inherit the user's directory ACL; use a private checkout.

Keycloak publishes only `127.0.0.1:8089` and uses a normal bridge created for
its unique Compose project, an in-memory database, no persistent data volume
and no restart policy. This bridge permits container egress; it is not an
outbound network filter. Inbound host access is restricted by the explicit
loopback port mapping. The host BFF keeps its exact provider allowlist,
disables proxies and redirects, and binds only the host loopback interface.
Docker Engine 28 or later is required for the documented loopback-port boundary.
Cleanup targets only the generated `rio-accounts-synthetic-<random>` project.
`run-bff` launches the built `services/rio-accounts/target/debug/rio-accounts-dev`
executable (with `.exe` on Windows) from the repository root.

## Safe startup diagnostics

If discovery fails, run `python verification/rio-accounts/fixture.py diagnostics`
before cleanup. The diagnostic reads provider logs privately, replaces every
generated client secret and user/admin password, scrubs other token-like values,
and emits only bounded startup error explanations, typed public container state
and validated published-port bindings. It does not print Docker environment fields.
Missing redaction inputs suppress all provider details. Raw provider logs,
configuration bodies and runtime files must not be exported.
The provider uses verbose startup internally so a cause can be diagnosed without
publishing an unfiltered stack trace.

## Browser verification

The policy/lifecycle checks run without Docker or OpenSSL execution:

```sh
python -m unittest discover -s verification/rio-accounts -p test_fixture.py
```

With the fixture and BFF running, open another terminal:

```sh
cd verification/rio-accounts
npm ci
npx playwright install --with-deps chromium
npm run check
npm test
```

The tests read generated login passwords only from the private local credential
file. Browser certificate acceptance is limited to test contexts for this
fixture. The sanitized result is `evidence/browser-summary.json`; runtime files,
environment dumps and authentication traces must not be uploaded.
A passing verification run does not change any HOLD gate.

## Private protocol: first RIO test on two physical phones

Status: **PREPARATION ONLY**. This protocol has not been executed on phones and
does not open ACCOUNT-1, real invitations, contact access or production.

### What the current slice proves

The current fixture can prove native OIDC login, server-bound synthetic identity,
isolated BFF sessions, CSRF protection, logout and expiry. Two browser contexts
are a useful preliminary check. They do not prove a RIO connection between two
physical devices: this account slice has no peer connection or message-delivery
endpoint.

`localhost` on a phone refers to that phone. The existing BFF deliberately binds
the developer computer's loopback interface, and its exact host, issuer and
callback checks are fixed for that local fixture. Copying its URL to two phones
cannot produce the requested device test.

### Smallest separate staging path

Use one existing developer computer and two test phones on the same private
Wi-Fi. Keep the account fixture unchanged. Prepare a separate, explicit
synthetic phone-test configuration before making any listener reachable:

1. Define two distinct, exact HTTPS names reachable from both phones: one for
   the BFF and one for the identity provider. Do not reuse one hostname with
   different ports, because browser cookies are not isolated by port.
2. Provide private DNS or equivalent routing for those names to the developer
   computer, and certificates trusted by both phones. A local test CA needs
   deliberate installation and removal on the two test devices; no certificate
   warning bypass may be treated as evidence of a trusted connection.
3. Use a gateway on the private LAN to forward only the intended BFF and IdP
   endpoints to their existing loopback listeners. Configure the separate BFF
   build with its exact public test origin, exact issuer/authorization/token/JWKS
   endpoints and exact HTTPS callback. Configure Keycloak's hostname and
   confidential-client redirect URI to the same agreed values. Preserve its
   endpoint allowlist, Secure host-only cookies, PKCE, nonce and state checks.
   A proxy host rewrite alone cannot make the current callback and Origin
   checks valid for phones.
4. Limit access to the test LAN/devices, generate a fresh synthetic realm and
   client secret for the run, and retain no real account or contact data.
   Confirm the environment still reports `SYNTHETIC_ONLY`, `ACCOUNT-1 HOLD`,
   `operativeAuthority NONE` and no contact access.
5. Implement and verify the RIO transport path that establishes a reciprocal
   connection between the two synthetic actors. Define its exact invitation,
   acceptance and test-message behavior, its session authorization and its
   sanitized connection evidence before calling the device test ready.

This is a preparation route, not a deployment instruction. It requires explicit
staging configuration, a trusted network/TLS setup and a working transport
slice. This change creates none of those external resources.

### Device rehearsal and acceptance

Record only `Phone A`, `Phone B`, OS/browser versions, the tested commit,
the two test hostnames and UTC scenario times. Do not record phone numbers,
device serials, email addresses, passwords, cookies, tokens or private keys.

| Step | Phone A | Phone B | Required result |
| --- | --- | --- | --- |
| Reachability | Open the agreed BFF HTTPS name | Open the same BFF HTTPS name | Both display the same tested build with trusted TLS |
| Synthetic login | Sign in as TST-alpha | Sign in as TST-beta | Server returns the corresponding fixed synthetic subject/account; HOLD status remains visible |
| Isolation | Read own account/session state | Read own account/session state | Neither phone obtains the other actor's state or authority |
| First RIO connection | Start the defined synthetic connection request | Accept that request through the defined transport path | Both devices receive one matching connection result linked to the two synthetic actors |
| Transport proof | Send a fresh synthetic challenge | Receive it and return a matching response | Delivery is observed on the other physical device; one connection identifier and timing pair match |
| Local logout | Log out the current BFF session | Keep its session open | A loses account/transport access; B remains bound to beta |
| Expiry/restart | Retry after the agreed session lifetime or service restart | Retry independently | Expired or cleared sessions receive an authorization failure and require fresh login |
| Cleanup | Close the test | Close the test | Stop gateway/IdP/BFF, remove generated secrets and temporary trust/DNS setup; keep only sanitized evidence |

The first genuine two-phone RIO connection is **PASS** only when the reciprocal
connection and challenge/response steps succeed on the two physical phones.
A successful pair of logins is recorded as **AUTH PASS / TRANSPORT NOT TESTED**.
Any missing staging, TLS, transport or physical-device evidence remains
**NOT RUN**. Automated localhost checks never replace the physical-device result.

## Version evidence

The exact image tag is pinned to the maintained release listed by the
[official Keycloak downloads page](https://www.keycloak.org/downloads), checked
on 2026-10-12. The immutable digest was observed in CI run 38378364460 on
2026-10-13 and is now pinned alongside the release tag.
The loopback development startup and realm import follow the
[official container guide](https://www.keycloak.org/server/containers).
The optional profile configuration follows the
[26.8.0 declarative user profile implementation](https://github.com/keycloak/keycloak/blob/26.8.0/services/src/main/java/org/keycloak/userprofile/DeclarativeUserProfileProvider.java).

The disabled unmanaged-attribute representation follows the actual
[26.8.0 UPConfig enum](https://github.com/keycloak/keycloak/blob/26.8.0/core/src/main/java/org/keycloak/representations/userprofile/config/UPConfig.java)
and [DefaultAttributes null-policy behavior](https://github.com/keycloak/keycloak/blob/26.8.0/server-spi-private/src/main/java/org/keycloak/userprofile/DefaultAttributes.java).

The per-project bridge and loopback publication follow Docker's
[Compose networking](https://docs.docker.com/compose/how-tos/networking/)
and [port publishing](https://docs.docker.com/engine/network/port-publishing/)
documentation. Docker's [internal network mode](https://docs.docker.com/reference/cli/docker/network/create/#network-internal-mode---internal)
restricts network routing. This runner showed failed published-port discovery
while the IdP was listening on an internal network; the fixture uses a normal
bridge so host discovery can reach the IdP.
