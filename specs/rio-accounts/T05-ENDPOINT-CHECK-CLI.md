# T05 — Offline endpoint-component command

Status: DRAFT / PLAN_ONLY / SYNTHETIC_ONLY. No launch, account or deployment authority.

This slice is stacked on draft #65 at frozen head `a6839777a37b5ea9cc39169384778e892f2121cf`. It exposes the existing strict `StagingEndpointPlan` through the real `rio-accounts-dev --check-staging-endpoints` executable. This checks only the endpoint component, not the separate full staging preflight in draft #55.

The command accepts exactly that one argument and reads a UTF-8 JSON document from standard input. Seven camelCase fields are required:

```json
{
  "bffOrigin": "https://rio.example.invalid",
  "idpIssuer": "https://identity.example.invalid/realms/rio-synthetic-staging",
  "callbackUrl": "https://rio.example.invalid/auth/callback",
  "discoveryUrl": "https://identity.example.invalid/realms/rio-synthetic-staging/.well-known/openid-configuration",
  "authorizationUrl": "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/auth",
  "tokenUrl": "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/token",
  "jwksUrl": "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/certs"
}
```

After a locked build, an operator can supply this document through stdin:

```sh
services/rio-accounts/target/debug/rio-accounts-dev --check-staging-endpoints < endpoint-component.json
```

The checker runs before async-runtime construction and `DevConfig::from_env`. It does not load runtime secrets, TLS files, storage, provider discovery or a listener. Stdin is limited to 4097 bytes of reading; the shared plan constructor rejects anything over 4096 bytes, including surrounding whitespace. Extra arguments are refused without reading stdin. `args_os` prevents non-UTF-8 argument panics from disclosing submitted bytes.

Only the existing fixed, value-free `RIO_STAGING_ENDPOINT_COMPONENT_V1` summary is printed on success (exit 0). Its `mode` remains `PLAN_ONLY`, all external verification flags remain false, and launch/deployment/accounts/contact remain closed. Invalid documents, read errors and unsupported checker arguments return exit 1 and fixed stderr `RIO staging endpoint component rejected.`; input values, error details and parsed origins are never diagnostics. Input must be closed/EOF supplied; an interactive open stdin can wait for more data up to the byte cap.

Blackbox tests execute the actual binary with an empty or deliberately invalid runtime environment. They cover exact closed-summary output, reserved `.invalid` endpoints, malformed/non-UTF-8/missing/duplicate/unknown fields, endpoint/host substitutions, exact 4096-byte acceptance and 4097-byte rejection, secret-canary non-disclosure, extra arguments and a Unix non-UTF-8 argv regression. The original loopback service, restore-fence command, provider binding and TLS/storage checks remain required in full CI. There is no staging runtime conversion, environment profile selector or dependency/lockfile change.

Exact-head full RIO and GO-13 must finish before an engineering PASS claim. Independent human acceptance #50, unresolved causes #51/#60/#64, physical Android/manual screen reader, real accounts, invitations, NOVA contact, staging and production remain HOLD. Endpoint validation is not DNS, TLS, IdP, database or deployment proof and never authorizes launch.
