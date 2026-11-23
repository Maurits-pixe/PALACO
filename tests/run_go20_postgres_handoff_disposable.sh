#!/usr/bin/env bash
# GO-20 v40: two isolated PostgreSQL instances, snapshot handoff ONLY.
# Not streaming replication, cluster leadership or real automatic failover.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "DENY: disposable CI guard absent" >&2; exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT current_database()')" == "go20test" ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT to_regclass('go20_v37.claims') IS NOT NULL")" == "t" ]]
tmp=$(mktemp -d)
name="go20-v40-secondary-$$"
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
if ! docker info >/dev/null 2>&1; then
  echo "DENY: disposable Docker engine unavailable" >&2; exit 2
fi
docker run -d --rm --name "$name" -e POSTGRES_DB=go20test \
  -e POSTGRES_USER=go20test -e POSTGRES_PASSWORD=go20test \
  -p 127.0.0.1:5433:5432 \
  postgres:17@sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f > "$tmp/container"
ready=no
for i in {1..100}; do
  if pg_isready -h 127.0.0.1 -p 5433 -U go20test -d go20test -q; then
    ready=yes; break
  fi
  sleep 0.2
done
[[ "$ready" == "yes" ]] || { echo "FAIL: secondary unavailable" >&2; exit 3; }
export PGPASSWORD=go20test
primary() { psql -XAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U go20test -d go20test -c "$1"; }
secondary() { psql -XAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5433 -U go20test -d go20test -c "$1"; }
export_sql="SELECT COALESCE(json_agg(row_to_json(t) ORDER BY request_id),'[]'::json) FROM (SELECT request_id,manifest_sha256,pin_sha256,segments_sha256 FROM go20_v37.claims) t"
snapshot() {
  primary "$export_sql" > "$tmp/primary.json"
  secondary "$export_sql" > "$tmp/secondary.json"
  PYTHONPATH=scripts python3 - "$tmp/primary.json" "$tmp/pin.json" <<'PY'
import json
import sys
from pathlib import Path
from pr_recovery_handoff import canonical, digest
data=json.loads(Path(sys.argv[1]).read_text())
Path(sys.argv[2]).write_text(json.dumps({
    "schema":"palaco.go20-restore-handoff-pin.v1",
    "primary_sha256":digest(canonical(data)),
    "minimum_rows":len(data),
}))
PY
}
compare() {
  python3 scripts/pr_recovery_handoff.py \
    --primary "$tmp/primary.json" \
    --candidate "$tmp/secondary.json" \
    --independent-pin "$tmp/pin.json" > "$tmp/verdict.json"
}
copy_fixture() {
  pg_dump -X -h 127.0.0.1 -p 5432 -U go20test -d go20test \
    --schema=go20_v37 --no-owner --no-acl > "$tmp/fixture.sql"
  psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5433 \
    -U go20test -d go20test -f "$tmp/fixture.sql" > /dev/null
}
copy_fixture
snapshot
compare
[[ "$(secondary 'SELECT count(*) FROM go20_v37.claims')" == "$(primary 'SELECT count(*) FROM go20_v37.claims')" ]]
# Create fresh primary-only commit. Candidate is stale and MUST fail closed.
a=$(printf 'a%.0s' {1..64})
b=$(printf 'b%.0s' {1..64})
c=$(printf 'c%.0s' {1..64})
[[ "$(primary "SELECT go20_v37.try_claim('v40-primary-only','$c','$a','$b')")" == "TEST_ONLY_COMMIT" ]]
snapshot
if compare; then
  echo "FAIL: stale replica handoff accepted" >&2; exit 3
fi
grep -q 'snapshot_divergence_or_missing_claims' "$tmp/verdict.json"
# Fresh snapshot transfer restores agreement; it does NOT promote or elect leader.
secondary 'DROP SCHEMA go20_v37 CASCADE' > /dev/null
copy_fixture
snapshot
compare
grep -q '"handoff_consistent": true' "$tmp/verdict.json"
grep -q '"failover_authorized": false' "$tmp/verdict.json"
# Prove that an inconsistent secondary row is not silently accepted.
secondary "UPDATE go20_v37.claims SET segments_sha256='$a' WHERE request_id='v40-primary-only'" >/dev/null
snapshot
if compare; then
  echo "FAIL: divergent secondary claim accepted" >&2; exit 3
fi
grep -q 'snapshot_divergence_or_missing_claims' "$tmp/verdict.json"
echo "GO-20 v40 isolated two-instance snapshot handoff, lag and divergence: PASS (HOLD/DENY)"
