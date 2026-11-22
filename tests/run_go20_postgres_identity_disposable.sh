#!/usr/bin/env bash
# GO-20 v13: session-principal negative tests in disposable PostgreSQL only.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "Refusing test outside disposable CI" >&2
  exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
psql -X -v ON_ERROR_STOP=1 -f tests/go20_postgres_identity_fixture.sql

query_as() {
  local principal="$1" sql="$2"
  psql -XAt -v ON_ERROR_STOP=1 -c "SET SESSION AUTHORIZATION $principal; $sql" | tail -n 1
}
must_deny() {
  local principal="$1" sql="$2"
  if psql -XAt -v ON_ERROR_STOP=1 -c "SET SESSION AUTHORIZATION $principal; $sql" >/dev/null 2>&1; then
    echo "Unexpected authorization for $principal" >&2
    exit 1
  fi
}
[[ "$(query_as go20_alpha 'SELECT identity_label FROM go20_test.principal_binding')" == synthetic-alpha ]]
[[ "$(query_as go20_beta 'SELECT identity_label FROM go20_test.principal_binding')" == synthetic-beta ]]
[[ "$(query_as go20_alpha 'SELECT count(*) FROM go20_test.principal_binding')" == 1 ]]
[[ "$(query_as go20_beta 'SELECT count(*) FROM go20_test.principal_binding')" == 1 ]]

# An untrusted GUC ("JWT sub" mimic) cannot alter a policy based on CURRENT_USER.
[[ "$(query_as go20_alpha "SELECT set_config('request.jwt.claim.sub','synthetic-beta',false); SELECT identity_label FROM go20_test.principal_binding")" == synthetic-alpha ]]
[[ "$(query_as go20_beta "SELECT set_config('request.jwt.claim.sub','synthetic-alpha',false); SELECT identity_label FROM go20_test.principal_binding")" == synthetic-beta ]]

# Crucially, SET SESSION AUTHORIZATION changes session_user to the low-privilege
# role. Unlike SET ROLE from a superuser session, hopping to the peer must fail.
must_deny go20_alpha 'SET ROLE go20_beta;'
must_deny go20_beta 'SET ROLE go20_alpha;'
must_deny go20_alpha "INSERT INTO go20_test.principal_binding VALUES ('go20_alpha','go20_alpha','forged');"
must_deny go20_beta "UPDATE go20_test.principal_binding SET identity_label='forged';"
must_deny go20_alpha "SELECT revision FROM go20_test.state;"
must_deny go20_beta "SELECT go20_test.try_consume(0,repeat('a',64),repeat('b',64),repeat('c',64));"

[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.principal_binding')" == 2 ]]
echo "GO-20 v13 synthetic principal and role-hop negative tests: PASS"
