#!/usr/bin/env bash
# GO-20 v38: terminate a disposable PostgreSQL client backend mid-transaction.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "DENY: disposable CI confirmation absent" >&2
  exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
query() { psql -XAt -v ON_ERROR_STOP=1 -c "$1"; }
a=$(printf 'a%.0s' {1..64})
b=$(printf 'b%.0s' {1..64})
c=$(printf 'c%.0s' {1..64})
d=$(printf 'd%.0s' {1..64})
[[ "$(query "SELECT to_regclass('go20_v37.claims') IS NOT NULL")" == "t" ]]
initial=$(query "SELECT COUNT(*) FROM go20_v37.claims")
[[ "$initial" =~ ^[0-9]+$ ]]
scratch=$(mktemp -d)
client_pid=""
cleanup() {
  if [[ -n "$client_pid" ]] && kill -0 "$client_pid" 2>/dev/null; then
    kill "$client_pid" 2>/dev/null || true
    wait "$client_pid" 2>/dev/null || true
  fi
  rm -rf "$scratch"
}
trap cleanup EXIT

# Target only this fixture's marked backend; no production server connections.
PGAPPNAME=go20_v38_fault_target psql -X -v ON_ERROR_STOP=1 \
  -c "BEGIN; SELECT go20_v37.try_claim('v38-killed','$d','$b','$a'); SELECT pg_sleep(25); COMMIT;" \
  >"$scratch/victim.out" 2>"$scratch/victim.err" &
client_pid=$!
backend=""
for i in {1..60}; do
  backend=$(query "SELECT pid FROM pg_stat_activity WHERE application_name='go20_v38_fault_target' AND state='active' AND query LIKE '%pg_sleep(25)%' AND pid<>pg_backend_pid() ORDER BY pid LIMIT 1")
  if [[ "$backend" =~ ^[0-9]+$ ]]; then break; fi
  sleep 0.1
done
if [[ ! "$backend" =~ ^[0-9]+$ ]]; then
  echo "FAIL: victim transaction not observed" >&2; exit 3
fi
[[ "$(query "SELECT pg_terminate_backend($backend)")" == "t" ]]
if wait "$client_pid"; then
  echo "FAIL: terminated backend completed successfully" >&2; exit 3
fi
client_pid=""
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "$initial" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims WHERE request_id='v38-killed'")" == "0" ]]
[[ "$(query "SELECT go20_v37.try_claim('v38-killed','$d','$b','$a')")" == "TEST_ONLY_COMMIT" ]]
[[ "$(query "SELECT go20_v37.try_claim('v38-killed','$d','$b','$a')")" == "REPLAY" ]]
[[ "$(query "SELECT go20_v37.try_claim('v38-killed','$d','$b','$c')")" == "CONFLICT" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "$((initial+1))" ]]

# An aborted statement without COMMIT also must not persist its claim.
if psql -X -v ON_ERROR_STOP=1 \
  -c "BEGIN; SET LOCAL statement_timeout='150ms'; SELECT go20_v37.try_claim('v38-timeout','$c','$b','$d'); SELECT pg_sleep(2); COMMIT;" \
  >"$scratch/timeout.out" 2>"$scratch/timeout.err"; then
  echo "FAIL: server-side statement timeout did not abort transaction" >&2; exit 3
fi
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims WHERE request_id='v38-timeout'")" == "0" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "$((initial+1))" ]]
[[ "$(query "SELECT go20_v37.try_claim('v38-timeout','$c','$b','$d')")" == "TEST_ONLY_COMMIT" ]]
[[ "$(query "SELECT go20_v37.try_claim('v38-timeout','$c','$b','$d')")" == "REPLAY" ]]
[[ "$(query "SELECT COUNT(*) FROM go20_v37.claims")" == "$((initial+2))" ]]
echo "GO-20 v38 disposable backend termination, timeout rollback, reconnect replay: PASS (HOLD/DENY)"
