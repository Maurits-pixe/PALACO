#!/usr/bin/env bash
set -Eeuo pipefail

if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3) )); then
  echo "Bash 4.3 of nieuwer is vereist." >&2
  exit 1
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APPS=("$ROOT/apps/neo-launcher" "$ROOT/apps/aether-frontend" "$ROOT/apps/bastion-frontend")

command -v node >/dev/null || { echo "Node.js 22.12+ ontbreekt." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm ontbreekt." >&2; exit 1; }
command -v cargo >/dev/null || { echo "Rust/Cargo ontbreekt." >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 12) ? 0 : 1)' ||
  { echo "Node.js 22.12+ is vereist." >&2; exit 1; }
[[ -n "${AETHER_MASTER_KEY:-}" && -n "${AETHER_API_TOKEN:-}" ]] ||
  { echo "Stel AETHER_MASTER_KEY en AETHER_API_TOKEN in (zie README.md)." >&2; exit 1; }

for app in "${APPS[@]}"; do
  [[ -f "$app/node_modules/vite/bin/vite.js" ]] ||
    { echo "Dependencies ontbreken in $app; voer daar npm ci uit." >&2; exit 1; }
  for file in localhost.pem localhost-key.pem; do
    [[ -s "$app/certs/$file" ]] ||
      { echo "TLS-bestand ontbreekt: $app/certs/$file (zie README.md)." >&2; exit 1; }
  done
done

# Separate process groups allow cleanup of npm and its Vite children together.
set -m
pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(cd -- "$ROOT/services/aether-engine" && exec cargo run --locked) &
pids+=("$!")

for app in "${APPS[@]}"; do
  (cd -P -- "$app" && exec npm run dev) &
  pids+=("$!")
done

echo "NEO: https://127.0.0.1:5173 | AETHER: https://localhost:5174 | BASTION: https://localhost:5175"
echo "AETHER-API: http://127.0.0.1:3006 (lokale proxy). Eerste compilatie kan even duren."
echo "Lokale ontwikkeling; BASTION-mutaties blijven gesloten. Ctrl+C stopt alle processen."
status=0
wait -n || status=$?
echo "Een component is gestopt; de overige processen worden afgesloten." >&2
(( status != 0 )) || status=1
exit "$status"
