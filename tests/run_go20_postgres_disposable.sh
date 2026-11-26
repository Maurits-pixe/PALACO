#!/usr/bin/env bash
# Disposable PostgreSQL CI database only. Never use a remote PGHOST.
set -euo pipefail
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "Refusing to run outside explicit disposable CI database" >&2
  exit 2
fi
psql -v ON_ERROR_STOP=1 -f tests/go20_postgres_contract.sql
psql -v ON_ERROR_STOP=1 -f tests/go20_postgres_contract_assertions.sql

# Reset synthetic fixture; both clients compete for the same revision.
psql -v ON_ERROR_STOP=1 -c "TRUNCATE go20_test.consumed; UPDATE go20_test.state SET revision=0,state_sha256=repeat('a',64);"
result_a="$(mktemp)"
result_b="$(mktemp)"
trap 'rm -f "$result_a" "$result_b"' EXIT
psql -XAt -v ON_ERROR_STOP=1 -c "SELECT go20_test.try_consume(0,repeat('a',64),repeat('b',64),repeat('1',64));" > "$result_a" &
a_pid=$!
psql -XAt -v ON_ERROR_STOP=1 -c "SELECT go20_test.try_consume(0,repeat('a',64),repeat('c',64),repeat('2',64));" > "$result_b" &
b_pid=$!
wait "$a_pid"
wait "$b_pid"
combined="$(cat "$result_a" "$result_b")"
[[ "$(printf '%s\n' "$combined" | grep -c '^TEST_ONLY_COMMIT$')" == 1 ]]
[[ "$(printf '%s\n' "$combined" | grep -c '^STALE_STATE$')" == 1 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT revision FROM go20_test.state')" == 1 ]]
[[ "$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM go20_test.consumed')" == 1 ]]
echo "GO-20 v11 disposable PostgreSQL integration: PASS"
