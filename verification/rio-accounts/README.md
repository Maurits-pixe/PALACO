# Synthetic RIO account fixture

This is the opt-in local verification environment for the first RIO account slice.
It uses only TST-alpha and TST-beta, with a disposable local PostgreSQL volume for
T03 storage and recovery verification. ACCOUNT-1, real invitations and production
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
the containers, their dedicated bridge, synthetic database volume and generated credentials with:

```sh
python verification/rio-accounts/fixture.py down
```

Run `prepare` again for a fresh realm, passwords, database credentials, client secret and certificate.
A runtime prepared before T03 must be explicitly stopped and removed with `down`
before a new database runtime can be created.
The certificate expires after one day. Do not reuse an old runtime after expiry.

## Identity and secret contract

| Item | Fixed fixture value |
| --- | --- |
| Keycloak image | `quay.io/keycloak/keycloak:26.8.0@sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741` |
| PostgreSQL image | `postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c` |
| Synthetic database | `127.0.0.1:8090`, role `rio_dev`, database `rio_synthetic` |
| Offline restore database | `rio_synthetic_restore` on the same loopback port |
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

No passwords, database URLs, private keys or client secrets are committed. Python generates
the confidential client secret as 32 random bytes encoded as 64 hexadecimal
characters; admin and user passwords are independently generated. The PostgreSQL
password is another independent 32 random bytes encoded as 64 hexadecimal characters.
The launcher never prints them. Do not print, upload or attach generated runtime
files or environment values as CI artifacts.

The ignored `.runtime/` directory contains:

- `bff.env`: `RIO_DEV_MODE=SYNTHETIC_ONLY`, `RIO_DEV_CLIENT_SECRET`,
  `RIO_DEV_TLS_CERT`, `RIO_DEV_TLS_KEY`, `RIO_DEV_DATABASE_URL`,
  `RIO_PG_TEST_URL` and `RIO_PG_RESTORE_TEST_URL`; consumed privately by the launcher.
  Both primary URLs have the exact form
  `postgresql://rio_dev:<generated-64-hex-password>@127.0.0.1:8090/rio_synthetic?sslmode=disable`;
  the restore URL changes only the database name to `rio_synthetic_restore`.
  The launcher never writes a connection URL into a process argument or public report.
- `test-credentials.json`: private `alpha` and `beta` objects, each with
  `username`, `subject` and a generated `password`; consumed by browser tests.
- `compose.env`: generated administrator and database passwords, absolute runtime path
  and unique Compose project name; consumed by the launcher only.
- `rio-synthetic-realm.json`: generated import containing the same client
  secret and synthetic passwords.
- `tls-cert.pem`, `tls-key.pem` and `metadata.json`: local TLS and cleanup state.
- When managed checks run: `bff-process.json`, `bff.log`, `db-backup.dump` and
  `durable-browser-state.json`. These are private, ignored and deleted by `down`.
  The browser state contains opaque test sessions and anti-forgery values, and
  the dump contains only the synthetic account schema. Neither is an evidence artifact.

On POSIX, the runtime directory is owner-only `0700`, and private files are
`0600`. The realm file is `0644` so Keycloak's container user can read its
single-file read-only bind mount; its host parent remains `0700`.
On Windows, these files inherit the user's directory ACL; use a private checkout.

Keycloak publishes only `127.0.0.1:8089` and keeps its in-memory database.
PostgreSQL publishes only `127.0.0.1:8090`, requires SCRAM authentication for
both local and host connections, and uses one volume scoped to the unique
Compose project. PostgreSQL 18 mounts that volume at `/var/lib/postgresql`.
Its synthetic data survives BFF and PostgreSQL process restarts, and `down --volumes`
removes it. Neither container has a restart policy. Both use the same normal
bridge created for the unique Compose project. This bridge permits container egress; it is not an
outbound network filter. Inbound host access is restricted by the explicit
loopback port mapping. The host BFF keeps its exact provider allowlist,
disables proxies and redirects, and binds only the host loopback interface.
Docker Engine 28 or later is required for the documented loopback-port boundary.
Cleanup targets only the generated `rio-accounts-synthetic-<random>` project.
`run-bff` launches the built `services/rio-accounts/target/debug/rio-accounts-dev`
executable (with `.exe` on Windows) from the repository root.

## Durable storage and controlled checks

PostgreSQL holds the two fictitious actors and account records, session reference
hashes, session generations, expiry and revocation state. Raw browser session
bearers are never stored in the account tables. Login state, nonce and PKCE
values remain in BFF memory, so an unfinished login fails closed after a restart.
The existing session limits remain 30 seconds idle and 60 seconds absolute.
These short limits apply to proof runs as well.

The local database connection deliberately uses no database TLS only for the
fixed synthetic loopback address above. It cannot select a remote hostname,
another port, another role or an arbitrary database. The normal BFF never serves
the restore database. This is a local test exception and does not configure a
production database.

Managed process control is available on Linux CI with Python 3.11 and kernel
pidfd support. Start the prepared fixture, run storage tests, then start its BFF:

```sh
python verification/rio-accounts/fixture.py run-storage-tests
python verification/rio-accounts/fixture.py start-bff
python verification/rio-accounts/fixture.py restart-bff
python verification/rio-accounts/fixture.py stop-bff
```

The controller verifies the fixed executable, process start time and a generated
private ownership token before signalling. It uses a pidfd so a reused numeric PID
cannot receive the signal. A restart must establish a changed owned process
generation while preserving the same PostgreSQL volume and connection settings.
Public restart evidence contains a boolean; process IDs and tokens stay private.
On other systems, use foreground `run-bff` and stop that owned terminal process.

`run-storage-tests` runs only the ignored `postgres_storage_contract` Rust test.
It excludes the two staged backup/restore harness tests. Captured output stays
private; only fixed numeric test summaries are emitted, and exactly one passing
test is required. `stop-db` and `start-db` target only PostgreSQL in this project;
start waits for an authenticated `SELECT 1`. They do not reset the volume.

For native recovery proof, stop the BFF and execute these commands consecutively:

```sh
python verification/rio-accounts/fixture.py stop-bff
python verification/rio-accounts/fixture.py prepare-restore-proof
python verification/rio-accounts/fixture.py backup-db
python verification/rio-accounts/fixture.py restore-db
```

The prepare test creates fresh, unexpired alpha/beta session hash markers and a
revoked marker. `backup-db` uses the pinned PostgreSQL container's actual
`pg_dump` in custom format, storing an owner-only archive capped at 16 MiB.
`restore-db` uses actual `pg_restore` into only `rio_synthetic_restore`; it
never replaces the original database. The restore test first reads the clone
directly to require both live markers to remain unexpired. It then connects
through the restore guard, which advances recovery generations, revokes all
snapshot sessions and clears login/bearer state before that store can be used.
Previously revoked markers remain closed. No restored BFF listener is started.
Failure leaves the clone offline and does not emit a passing recovery result.

These stages run after compilation, immediately one after another, within the
unchanged session lifetime. Archive creation or a successful restore command
alone does not establish the revocation result. Cleanup removes both databases
with their project volume, the archive and all known private runtime files.

## Safe startup diagnostics

If discovery fails, run `python verification/rio-accounts/fixture.py diagnostics`
before cleanup. The diagnostic reads provider logs privately, replaces every
generated client secret and user/admin password, scrubs other token-like values,
and emits only bounded startup error explanations, typed public container state
and validated published-port bindings. It does not print Docker environment fields.
Missing redaction inputs suppress all provider details. The generated database
password/URLs and private process/browser values are also included in redaction.
Use `fixture.py db-diagnostics` for only typed PostgreSQL state, validated
loopback port bindings and fixed startup-reason booleans. It reads logs privately
and never exports database log text or environment fields. Raw provider logs,
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
A passing verification run does not change any HOLD gate. The original five
real OIDC checks remain separate from the durable checks.

After `npm test`, the workflow runs the following phases in the same prepared
environment:

```sh
RIO_DURABLE_BROWSER_PHASE=outage npx playwright test --config=playwright.durable.config.mjs
RIO_DURABLE_BROWSER_PHASE=prepare npx playwright test --config=playwright.durable.config.mjs
python fixture.py restart-bff
RIO_DURABLE_BROWSER_PHASE=revoke npx playwright test --config=playwright.durable.config.mjs
python fixture.py restart-bff
RIO_DURABLE_BROWSER_PHASE=verify npx playwright test --config=playwright.durable.config.mjs
```

The outage case stops only this PostgreSQL container, requires both own-account
access and login start to return 503, restarts the database, restarts the owned BFF process and requires the same
cookie to recover its own account. Database uncertainty permanently closes access
in the current BFF process; a fresh process must establish a fresh connection. It runs before preparing durable sessions.

Prepare performs three actual OIDC logins: alpha, alpha peer and beta. Revoke
after the first BFF restart first requires all three sessions to survive with
unchanged anti-forgery values, rejects cross-session/cross-actor anti-forgery
values, then logs out all alpha sessions through the native UI. Both alpha
cookies must be unauthorized while beta remains valid. Verify after the second
restart requires retained alpha cookies to remain unauthorized and beta to
remain valid. The surviving beta prevents expiry from being mistaken for a
successful revocation proof.

Each phase emits only its sanitized `evidence/browser-durable-PHASE-summary.json`.
The private saved state is `.runtime/durable-browser-state.json`, mode 0600,
deleted after final verification and also removed by `down` after failures.
A managed Linux CI run is still required before claiming these new checks pass.

## Mobile account and local Studio checks (T04)

The same BFF origin serves the mobile account page, `/app.js` and `/app.css`.
It reads only the signed-in fictitious account and its own stored receipt. The
native checkbox is never preselected; an explicit confirmation applies only to
`RIO_SYNTHETIC_SESSION_TEST_V1`. Revocation and both logout actions remain
server-checked. A conflicting revision reloads the current receipt and requires
a fresh choice. Expired or uncertain account state clears the protected view;
recovery requires an explicit check.

`GET /api/consent` reads the current session's own receipt. `POST /api/consent`
requires the same-origin session, its `X-CSRF-Token` and exactly the JSON keys
`scope`, `granted` and `revision`. There is no caller-selected account or owner.
The actual PostgreSQL/router proof runs before the BFF starts:

```sh
python verification/rio-accounts/fixture.py run-consent-http-tests
```

After the existing default and durable browser checks, run:

```sh
cd verification/rio-accounts
npx playwright test --config=mobile/playwright.config.mjs
```

This suite exercises Chromium Android emulation and desktop keyboard/native
control behavior, 320 CSS-pixel reflow, local concept file download/import,
real receipt ownership/CSRF/revision checks, expiry and a controlled database
outage with explicit recovery. Browser emulation and DOM/ARIA checks do not
establish a physical Android or screen-reader acceptance result.

Studio keeps only an in-memory title (80 characters) and note (2,000 characters).
Its explicit JSON export/import uses `RIO_LOCAL_DRAFT_V1`, marks the data
`UNVERIFIED`, keeps all authority/consent flags closed and caps the file at
12,288 UTF-8 bytes. It never posts that content, stores a login in the browser
or converts imported data into an identity or consent. Page close/reload clears
the in-memory concept. See [the T04 contract](../../specs/rio-accounts/T04-MOBILE.md).

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
| Expiry/restart | Retry after the agreed session lifetime or service restart | Retry independently | Ordinary restarts preserve live sessions; expired/revoked sessions fail, and recovery restores fence all snapshot sessions |
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

The PostgreSQL version follows the [official support policy](https://www.postgresql.org/support/versioning/)
and [18.6 release announcement](https://www.postgresql.org/about/news/postgresql-186-1711-1615-1519-1424-and-19-beta-3-released-3365/),
checked on 2026-10-13. The immutable multi-platform manifest digest comes from
[Docker Library's published 18.6-bookworm registry metadata](https://github.com/docker-library/repo-info/blob/master/repos/postgres/remote/18.6-bookworm.md).
Image authentication and the PostgreSQL 18 data mount follow the
[official PostgreSQL image documentation](https://hub.docker.com/_/postgres)
and [official image entrypoint](https://github.com/docker-library/postgres/blob/master/18/bookworm/docker-entrypoint.sh).
Native archive operations follow PostgreSQL's
[pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html) and
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html) references.
