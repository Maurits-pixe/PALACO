#!/usr/bin/env bash
# GO-20 v12: negative authorisation tests in disposable CI PostgreSQL.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "Refusing test outside disposable CI" >&2
  exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
psql -X -v ON_ERROR_STOP=1 -f tests/go20_postgres_rls_fixture.sql

query_as() {
  local role="$1" sql="$2"
  psql -XAt -v ON_ERROR_STOP=1 -c "SET ROLE $role; $sql" | tail -n 1
}
must_deny() {
  local role="$1" sql="$2"
  if psql -XAt -v ON_ERROR_STOP=1 -c "SET ROLE $role; $sql" >/dev/null 2>&1; then
    echo "UNEXPECTED ACCESS: $role" >&2
    exit 1
  fi
}
[[ "$(query_as go20_alpha 'SELECT COUNT(*) FROM go20_test.tenant_evidence;')" == 1 ]]
[[ "$(query_as go20_beta 'SELECT COUNT(*) FROM go20_test.tenant_evidence;')" == 1 ]]
[[ "$(query_as go20_alpha 'SELECT entry_sha256 FROM go20_test.tenant_evidence;')" == "$(printf 'a%.0s' {1..64})" ]]
[[ "$(query_as go20_beta 'SELECT entry_sha256 FROM go20_test.tenant_evidence;')" == "$(printf 'b%.0s' {1..64})" ]]

must_deny go20_alpha "INSERT INTO go20_test.tenant_evidence VALUES ('go20_alpha', repeat('c',64));"
must_deny go20_beta "UPDATE go20_test.tenant_evidence SET entry_sha256=repeat('c',64);"
must_deny go20_alpha "SELECT revision FROM go20_test.state;"
must_deny go20_beta "SELECT entry_sha256 FROM go20_test.consumed;"
must_deny go20_alpha "SELECT go20_test.try_consume(0,repeat('a',64),repeat('b',64),repeat('c',64));"
must_deny go20_beta "SELECT go20_test.try_consume(0,repeat('a',64),repeat('b',64),repeat('c',64));"

[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT revision FROM go20_test.state')" == 0 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.consumed')" == 0 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.tenant_evidence')" == 2 ]]
echo "GO-20 v12 PostgreSQL role/RLS negative tests: PASS"
