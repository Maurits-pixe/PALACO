# Synthetic RIO account fixture

This is the opt-in local verification environment for the first RIO account slice.
It uses only TST-alpha and TST-beta. ACCOUNT-1, real invitations and production
remain **HOLD**. There is no Render deployment or production identity connection.

## Prerequisites and launch

Use Python 3.11 or later, OpenSSL, Docker with Compose v2, and the repository's
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
the container, its isolated network and generated credentials with:

```sh
python verification/rio-accounts/fixture.py down
```

Run `prepare` again for a fresh realm, passwords, client secret and certificate.
The certificate expires after one day. Do not reuse an old runtime after expiry.

## Identity and secret contract

| Item | Fixed fixture value |
| --- | --- |
| Keycloak image | `quay.io/keycloak/keycloak:26.8.0` |
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

Keycloak publishes only `127.0.0.1:8089` and uses an internal Compose network,
an in-memory database, no persistent data volume and no restart policy.
Cleanup targets only the generated `rio-accounts-synthetic-<random>` project.
`run-bff` launches the built `services/rio-accounts/target/debug/rio-accounts-dev`
executable (with `.exe` on Windows) from the repository root.

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

## Version evidence

The exact image tag is pinned to the maintained release listed by the
[official Keycloak downloads page](https://www.keycloak.org/downloads), checked
on 2026-10-12. An immutable registry digest must be recorded after the first
verified image pull; this fixture currently pins the release tag, not a digest.
The loopback development startup and realm import follow the
[official container guide](https://www.keycloak.org/server/containers).
The optional profile configuration follows the
[26.8.0 declarative user profile implementation](https://github.com/keycloak/keycloak/blob/26.8.0/services/src/main/java/org/keycloak/userprofile/DeclarativeUserProfileProvider.java).
