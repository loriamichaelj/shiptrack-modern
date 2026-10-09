#!/usr/bin/env bash
# Post-deploy smoke test through the ALB, addressed to the modern stack with the test token.
#
#   BASE_URL=... TEST_TOKEN=... scripts/smoke.sh [platform-contract-dir]
#
# Part one needs nothing but curl: the stack header must say "modern" (a missing or wrong token would
# fall through to the weighted rules and test legacy), readiness must be green, and the API must
# answer. Part two runs the platform's contract smoke suite when its directory is given.
set -euo pipefail

: "${BASE_URL:?BASE_URL is required}"
: "${TEST_TOKEN:?TEST_TOKEN is required}"
base=${BASE_URL%/}
contract_dir=${1:-}

fetch() {
  local path=$1
  curl -sS --max-time 15 -D - -o /dev/null \
    -H "X-ShipTrack-Target: modern" -H "X-ShipTrack-Test-Token: ${TEST_TOKEN}" \
    "${base}${path}"
}

check() {
  local path=$1 want=$2 headers status stack
  headers=$(fetch "$path")
  status=$(printf '%s' "$headers" | awk 'NR==1 {print $2}')
  stack=$(printf '%s' "$headers" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-shiptrack-stack" {print $2}')
  if [[ "$status" != "$want" ]]; then
    echo "FAIL ${path}: expected ${want}, got ${status:-no response}" >&2
    return 1
  fi
  if [[ "$stack" != "modern" ]]; then
    echo "FAIL ${path}: X-ShipTrack-Stack is '${stack:-missing}', not modern (routing fell through?)" >&2
    return 1
  fi
  echo "ok   ${path} -> ${status} from modern"
}

# A rollout can finish before the ALB has marked the new targets healthy.
for attempt in $(seq 1 12); do
  if check /readyz 200 2>/dev/null; then break; fi
  if [[ "$attempt" == 12 ]]; then check /readyz 200; fi
  sleep 10
done
check /healthz 200
check "/api/v1/shipments?limit=1" 200
check /ui/ 200

if [[ -n "$contract_dir" ]]; then
  echo "running the contract smoke suite"
  (cd "$contract_dir" && TARGET=modern BASE_URL="$base" TEST_TOKEN="$TEST_TOKEN" uv run --frozen pytest -m smoke -q)
else
  echo "contract suite skipped: no directory given"
fi
