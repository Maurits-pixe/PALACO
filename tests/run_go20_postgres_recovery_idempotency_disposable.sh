#!/usr/bin/env bash
# GO-20 v37: disposable local PostgreSQL only; not a production migration.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "DENY: disposable CI confirmation absent" >&2; exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
psql -X -v ON_ERROR_STOP=1 -f tests/go20_postgres_recovery_idempotency.sql
query() { psql -XAt -v ON_ERROR_STOP=1 -c "$1"; }
a=$(printf 'a%.0s' {1..64})
b=$(printf 'b%.0s' {1..64})
c=$(printf 'c%.0s' {1..64})
d=$(printf 'd%.0s' {1..64})
[[ "$(query "SELECT go20_v37.try_claim('restore-1','$a','$b','$c')")" == "TEST_ONLY_COMMIT" ]]
# New database sessions must see the same ledger.
[[ "$(query "SELECT go20_v37.try_claim('restore-1','$a','$b','$c')")" == "REPLAY" ]]
[[ "$(query "SELECT go20_v37.try_claim('restore-2','$a','$b','$c')")" == "REPLAY" ]]
[[ "$(query "SELECT go20_v37.try_claim('restore-1','$a','$b','$d')")" == "CONFLICT" ]]
[[ "$(query "SELECT go20_v37.try_claim('','$a','$b','$c')")" == "INVALID_INPUT" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "1" ]]
# Simulated explicit abort must leave no partial claim.
query "BEGIN; SELECT go20_v37.try_claim('aborted','$d','$b','$c'); ROLLBACK;" >/dev/null
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "1" ]]
# A session closing before commit must roll back in PostgreSQL.
query "BEGIN; SELECT go20_v37.try_claim('disconnected','$d','$b','$d');" >/dev/null
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "1" ]]
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for i in {1..8}; do
  (query "SELECT go20_v37.try_claim('race-$i','$d','$b','$c')" > "$tmp/$i") &
done
wait
[[ "$(grep -h '^TEST_ONLY_COMMIT$' "$tmp"/{1..8} | wc -l)" -eq 1 ]]
[[ "$(grep -h '^REPLAY$' "$tmp"/{1..8} | wc -l)" -eq 7 ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "2" ]]
[[ "$(query "SELECT go20_v37.try_claim('after-restart','$d','$b','$c')")" == "REPLAY" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "2" ]]
echo "GO-20 v37 disposable PostgreSQL idempotency/restart/rollback: PASS (HOLD/DENY)"
