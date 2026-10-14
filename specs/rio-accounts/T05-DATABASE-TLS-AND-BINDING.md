# T05 — Synthetic PostgreSQL TLS and issuer/subject binding

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY. ACCOUNT-1, account staging deployment,
personal accounts, independent human acceptance and production remain HOLD.
Operative authority: NONE.

## Problem and resulting behavior

The existing durable dev store used the fixed local plaintext PostgreSQL fixture.
Its session writer received a fictional account hint after OIDC verification,
but did not independently resolve the stored issuer/subject binding. This slice
adds an opt-in verified TLS transport for the same closed synthetic schema and
requires an exact durable issuer/subject match before session creation or rotation.
It does not establish the cause of the historical intermittent mobile login
failure in issue #51, which remains OPEN / UNKNOWN.

## Closed transport contract

`SyntheticTlsDbConfig` has private PostgreSQL and Rustls fields, no Debug
implementation, and no credential accessors. The public constructor validates a
canonical lowercase ASCII DNS host without URI/port/options, a 64–128 character
hex password and one complete DER CA certificate (maximum 16 KiB). It rejects
missing/duplicate BasicConstraints, CA=false, non-V3, PEM, concatenated
certificates and trailing bytes before network I/O. Structural validation does
not prove the authority or provenance of the supplied trust anchor.

Role `rio_dev`, database `rio_synthetic_tls`, port 5432, TLS requirement and
SCRAM channel binding requirement are fixed. The trust store starts empty and
contains only the supplied CA. The maintained Rustls adapter validates the server
chain and hostname with an explicit ring provider and safe protocol defaults.
There is no custom bypass verifier, system-root fallback or plaintext retry.
Connection setup and current-connection verification are bounded by existing
style timeouts (8 and 5 seconds). Cancellation or connection-task exit clears
health; unsuccessful initial verification aborts the connection task.

After the actual connection is established, the connector checks
`SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()`.
It requires ssl=true and TLSv1.2/TLSv1.3. A server-level ssl setting alone is not
accepted as evidence that this connection is encrypted.

Only cfg(test) addressing can use localhost, hostaddr 127.0.0.1 and the fixed
8091/8092 ports. The application launcher and AppState retain the existing dev
profile and database connection. No environment selector or staging launcher
is introduced; the TLS store constructor retains the SYNTHETIC_ONLY guard.

Pinned new dependencies: tokio-postgres-rustls 0.14.0, rustls 0.23.45 and
x509-cert 0.2.5. Cargo.lock is committed and all CI Cargo verification uses
`--locked`. The temporary dependency-resolution workflow is removed.

## Transactional identity binding

The callback passes the issuer from the same immutable verified endpoint policy
and the subject from the cryptographically verified ID token into
`replace_session_bound`. The fictional account hint must agree with the durable
binding. In the existing timed transaction, the writer selects the exact
`auth_bindings.issuer + subject` joined to `accounts`, using
`FOR SHARE OF b,a`. It derives account ID, owner, tenant, status and epoch from
that row before predecessor rotation, session insertion or success audit.

Missing/wrong issuer, unknown subject, cross-account hints, disabled accounts and
epoch mismatches fail closed. Negative cases check session, audit and outbox
counts plus predecessor rotation/family state. The normal account epoch
revocation route is retained. Arbitrary external deletion of a binding is not
claimed to invalidate an already issued cookie automatically.

The existing migration continues to seed only the two fictional dev actors and
their fixed HTTP dev issuer. An HTTPS staging issuer is deliberately not seeded;
the TLS test explicitly verifies that an HTTPS issuer with the same subject is
rejected. A real IdP binding, invitation and issuer/activation authority still
require separate reviewed work.

## Disposable proof and privacy

`tls_fixture.py check` is an explicit Linux CI/local-test operation. It creates
one exclusive private directory and an unpredictable owned Compose project,
fixes Docker to the local Unix socket and removes remote Docker/Compose/PG
configuration from the child environment. TLS and plaintext controls use separate
PostgreSQL 18.6 containers with the existing digest pin, the same fresh private
credentials and database name. Both published ports bind only 127.0.0.1.

A one-day CA signs a server certificate for localhost. A distinct one-day CA is
the negative trust control. Host inputs are directory mode 0700/files 0600.
The container copies selected server files as root into a postgres-owned private
directory; it never makes a host private key world readable. The TLS HBA rejects
non-TLS TCP; readiness uses authenticated SCRAM over a container Unix socket,
not an unauthenticated TCP exception.

The runner selects exactly one ignored Rust test, checks its selection and result,
and emits only a fixed case identifier and whitelisted summary. Private raw logs,
keys and credentials are not printed or uploaded. Cleanup verifies its ownership
marker and file identities, removes only its named namespace, checks containers,
network and volumes are absent, then removes only its known private files.
Unowned/existing directories or tampered files fail closed and are not deleted.

Actual proof assertions, separate from harness test counts:

1. Authenticated plaintext control succeeds with ssl=false.
2. TLS connection uses ssl=true and TLSv1.2/TLSv1.3, and closed storage migrates.
3. A wrong CA is rejected.
4. A wrong server hostname is rejected.
5. A plaintext server is rejected by the TLS connector; no fallback.
6. The TLS server rejects a plaintext connection with otherwise correct credentials.
7. Exact dev issuer/subject creates a bound session; the staging issuer does not
   mutate session/audit/outbox/predecessor state.
8. Logout invalidates the issued session.

Ten mocked runner checks cover lifecycle, privacy, test selection, cancellation,
unowned directories, symlinks, tampering, cleanup failures, remote Docker
configuration and leftover resources. They do not substitute for the actual TLS
proof. Five connector unit tests and two compile-fail doctests check input and
immutable policy boundaries. Existing real Keycloak, database, browser, mobile,
backup/restore and retry-free repeat probes remain required.

## Evidence and release boundary

CI evidence must be recorded against the exact commit and kept alongside any
initial failures. Passing synthetic tests is not independent human security
acceptance, personal identity issuance, an operational staging deployment or a
production approval. No Render resources, provider accounts, credentials,
invitations, mails, mandates or activation rights are created by this slice.

Primary implementation references:
- [tokio-postgres-rustls 0.14.0](https://docs.rs/tokio-postgres-rustls/0.14.0/tokio_postgres_rustls/)
- [tokio-postgres SSL modes](https://docs.rs/tokio-postgres/latest/tokio_postgres/config/enum.SslMode.html)
- [PostgreSQL TLS](https://www.postgresql.org/docs/18/ssl-tcp.html)
- [Current-connection pg_stat_ssl](https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-SSL-VIEW)
