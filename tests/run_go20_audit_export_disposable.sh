#!/usr/bin/env bash
# GO-20 v16: controlled export of synthetic audit rows from disposable CI only.
set -euo pipefail
if [[ "$GITHUB_ACTIONS" != "true" || "$CI_GO20_DISPOSABLE_PG" != "yes" ]]; then
  echo "Refusing outside disposable CI" >&2
  exit 2
fi
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=go20test PGDATABASE=go20test PGPASSWORD=go20test
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
# JSON row format is produced by PostgreSQL (no client CSV or delimiter ambiguity).
psql -XAt -v ON_ERROR_STOP=1 -c \
  "SELECT row_to_json(a)::text FROM (SELECT id, operation, actor_role::text AS actor_role, tenant_role::text AS tenant_role, entry_sha256 FROM go20_test.audit_events ORDER BY id) a" \
  > "$workdir/source.ndjson"
python3 scripts/pr_audit_export.py \
  --input-ndjson "$workdir/source.ndjson" \
  --output-export "$workdir/export.json" \
  --output-manifest "$workdir/manifest.json"

# Capture the generated head as a FIXED benchmark for subsequent negative checks.
# This benchmark is NOT independent attestation and MUST NOT grant authority.
head="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["calculated_head_sha256"])' "$workdir/manifest.json")"
python3 scripts/pr_audit_integrity.py "$workdir/export.json" --expected-head-sha256 "$head"

# A modified export must be rejected against the previously captured test anchor.
python3 - "$workdir/export.json" "$workdir/tampered.json" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["events"]
payload["events"][0]["tenant_role"] = "go20_forged"
Path(sys.argv[2]).write_text(json.dumps(payload), encoding="utf-8")
PY
if python3 scripts/pr_audit_integrity.py "$workdir/tampered.json" --expected-head-sha256 "$head"; then
  echo "Tampered audit export was accepted" >&2
  exit 1
fi
echo "GO-20 v16 disposable audit export bridge: PASS (technical test only; HOLD/DENY)"
