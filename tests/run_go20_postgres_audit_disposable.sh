#!/usr/bin/env bash
# GO-20 v14: isolated multi-tenant attacks and auditable writes in CI only.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "Refusing audit tests outside disposable CI" >&2
  exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
psql -X -v ON_ERROR_STOP=1 -f tests/go20_postgres_audit_fixture.sql

query_as() {
  local principal="$1" sql="$2"
  psql -XAt -v ON_ERROR_STOP=1 -c "SET SESSION AUTHORIZATION $principal; $sql" | tail -n 1
}
must_deny() {
  local principal="$1" sql="$2"
  if psql -XAt -v ON_ERROR_STOP=1 -c "SET SESSION AUTHORIZATION $principal; $sql" >/dev/null 2>&1; then
    echo "UNEXPECTED ACCESS: $principal" >&2
    exit 1
  fi
}
audit_before="$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.audit_events')"
rows_before="$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.tenant_evidence')"
revision_before="$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT revision FROM go20_test.state')"

# Explicit filtering, join, and client-controlled claim spoofing cannot cross RLS.
[[ "$(query_as go20_alpha "SELECT count(*) FROM go20_test.tenant_evidence WHERE tenant_role='go20_beta'")" == 0 ]]
[[ "$(query_as go20_beta "SELECT count(*) FROM go20_test.tenant_evidence WHERE tenant_role='go20_alpha'")" == 0 ]]
[[ "$(query_as go20_alpha "SELECT count(*) FROM go20_test.tenant_evidence e JOIN go20_test.principal_binding p ON e.tenant_role=p.tenant_role")" == 1 ]]
[[ "$(query_as go20_beta "SELECT count(*) FROM go20_test.tenant_evidence e JOIN go20_test.principal_binding p ON e.tenant_role=p.tenant_role")" == 1 ]]
[[ "$(query_as go20_alpha "SELECT set_config('request.jwt.claim.role','go20_beta',false); SELECT count(*) FROM go20_test.tenant_evidence WHERE tenant_role='go20_beta'")" == 0 ]]
[[ "$(query_as go20_beta "SELECT set_config('request.jwt.claim.role','go20_alpha',false); SELECT count(*) FROM go20_test.tenant_evidence WHERE tenant_role='go20_alpha'")" == 0 ]]

must_deny go20_alpha 'SET ROLE go20_beta;'
must_deny go20_beta 'SET ROLE go20_alpha;'
must_deny go20_alpha "SET row_security=off; SELECT count(*) FROM go20_test.tenant_evidence;"
must_deny go20_beta "SET row_security=off; SELECT count(*) FROM go20_test.principal_binding;"
must_deny go20_alpha "DELETE FROM go20_test.tenant_evidence WHERE tenant_role='go20_beta';"
must_deny go20_beta "INSERT INTO go20_test.tenant_evidence VALUES ('go20_alpha',repeat('c',64));"
must_deny go20_alpha "SELECT * FROM go20_test.audit_events;"
must_deny go20_beta "DELETE FROM go20_test.audit_events;"
must_deny go20_alpha "SELECT revision FROM go20_test.state;"

[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.audit_events')" == "$audit_before" ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.tenant_evidence')" == "$rows_before" ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT revision FROM go20_test.state')" == "$revision_before" ]]

# The privileged synthetic fixture owner performs a controlled test-only write.
psql -X -v ON_ERROR_STOP=1 -c "INSERT INTO go20_test.tenant_evidence VALUES ('go20_alpha',repeat('c',64));"
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM go20_test.audit_events WHERE operation='INSERT' AND tenant_role='go20_alpha' AND entry_sha256=repeat('c',64)")" == 1 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.audit_events')" == "$((audit_before+1))" ]]

# Rollback of a synthetic write must rollback its audit event, too.
psql -X -v ON_ERROR_STOP=1 -c "BEGIN; INSERT INTO go20_test.tenant_evidence VALUES ('go20_beta',repeat('d',64)); ROLLBACK;"
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM go20_test.tenant_evidence WHERE entry_sha256=repeat('d',64)")" == 0 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.audit_events')" == "$((audit_before+1))" ]]
must_deny go20test "DELETE FROM go20_test.audit_events WHERE operation='INSERT';"
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.audit_events')" == "$((audit_before+1))" ]]
echo "GO-20 v14 disposable cross-tenant and audit invariants: PASS"
