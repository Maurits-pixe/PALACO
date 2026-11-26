#!/usr/bin/env bash
# GO-20 v39: SIGKILL/restart exclusively the disposable GitHub Actions PG service.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "DENY: disposable CI guard absent" >&2; exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
query() { psql -XAt -v ON_ERROR_STOP=1 -c "$1"; }
a=$(printf 'a%.0s' {1..64})
b=$(printf 'b%.0s' {1..64})
c=$(printf 'c%.0s' {1..64})
d=$(printf 'd%.0s' {1..64})
[[ "$(query "SELECT current_database()")" == "go20test" ]]
[[ "$(query "SELECT to_regclass('go20_v37.claims') IS NOT NULL")" == "t" ]]
container=$(docker ps --filter 'publish=5432' --format '{{.ID}}')
if [[ -z "$container" || "$container" == *$'\n'* ]]; then
  echo "DENY: disposable service container not unique" >&2; exit 2
fi
image=$(docker inspect --format '{{.Config.Image}}' "$container")
if [[ "$image" != postgres:17* ]]; then
  echo "DENY: unexpected service image" >&2; exit 2
fi
envs=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container")
if ! grep -qx 'POSTGRES_DB=go20test' <<<"$envs"; then
  echo "DENY: wrong container database" >&2; exit 2
fi

[[ "$(query "SELECT go20_v37.try_claim('v39-durable','$a','$b','$d')")" == "TEST_ONLY_COMMIT" ]]
before=$(query "SELECT COUNT(*) FROM go20_v37.claims")
[[ "$before" =~ ^[0-9]+$ ]]
scratch=$(mktemp -d)
victim=""
cleanup() {
  if [[ -n "$victim" ]] && kill -0 "$victim" 2>/dev/null; then
    kill "$victim" 2>/dev/null || true
    wait "$victim" 2>/dev/null || true
  fi
  rm -rf "$scratch"
}
trap cleanup EXIT

# An inserted, uncommitted claim remains open while pg_sleep is active.
PGAPPNAME=go20_v39_uncommitted psql -X -v ON_ERROR_STOP=1 \
  -c "BEGIN; SELECT go20_v37.try_claim('v39-uncommitted','$d','$c','$a'); SELECT pg_sleep(25); COMMIT;" \
  >"$scratch/victim.out" 2>"$scratch/victim.err" &
victim=$!
active=""
for i in {1..100}; do
  active=$(query "SELECT count(*) FROM pg_stat_activity WHERE application_name='go20_v39_uncommitted' AND state='active' AND query LIKE '%pg_sleep(25)%'")
  if [[ "$active" == "1" ]]; then break; fi
  sleep 0.1
done
if [[ "$active" != "1" ]]; then
  echo "FAIL: uncommitted transaction not observed" >&2; exit 3
fi
docker kill --signal=SIGKILL "$container" >/dev/null
if wait "$victim"; then
  echo "FAIL: uncommitted transaction finished after SIGKILL" >&2; exit 3
fi
victim=""
docker start "$container" >/dev/null
ready=no
for i in {1..100}; do
  if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -q; then
    ready=yes; break
  fi
  sleep 0.2
done
if [[ "$ready" != "yes" ]]; then
  echo "FAIL: PostgreSQL did not restart" >&2; exit 3
fi
[[ "$(query "SELECT count(*) FROM go20_v37.claims WHERE request_id='v39-durable'")" == "1" ]]
[[ "$(query "SELECT count(*) FROM go20_v37.claims WHERE request_id='v39-uncommitted'")" == "0" ]]
[[ "$(query "SELECT count(*) FROM go20_v37.claims")" == "$before" ]]
[[ "$(query "SELECT go20_v37.try_claim('v39-durable','$a','$b','$d')")" == "REPLAY" ]]
[[ "$(query "SELECT go20_v37.try_claim('v39-durable','$a','$b','$c')")" == "CONFLICT" ]]
[[ "$(query "SELECT go20_v37.try_claim('v39-uncommitted','$d','$c','$a')")" == "TEST_ONLY_COMMIT" ]]
[[ "$(query "SELECT go20_v37.try_claim('v39-uncommitted','$d','$c','$a')")" == "REPLAY" ]]
[[ "$(query "SELECT count(*) FROM go20_v37.claims")" == "$((before+1))" ]]
echo "GO-20 v39 disposable PG hard-stop/restart WAL, rollback and replay: PASS (HOLD/DENY)"
