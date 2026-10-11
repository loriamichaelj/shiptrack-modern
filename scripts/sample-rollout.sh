#!/usr/bin/env bash
# Print what the cluster is doing while `helm upgrade --atomic --wait` runs, so a rollout that times
# out leaves evidence. An atomic upgrade uninstalls the release when it fails, and the pods go with
# it, so this has to sample during the wait rather than look afterwards.
# Usage: scripts/sample-rollout.sh <namespace> [interval-seconds]
#
# Read-only: it only gets, lists, and reads logs. The deploy role may read pods, pods/log, events,
# and target group bindings in the namespace. Output is for a public log, so account IDs, ARNs, and
# node names are masked, and each pod's log is limited to its last lines.
set -uo pipefail

namespace=${1:?usage: sample-rollout.sh <namespace> [interval-seconds]}
interval=${2:-30}

mask() {
  sed -E \
    -e 's/[0-9]{12}/<ACCOUNT_ID>/g' \
    -e 's/arn:aws[a-z-]*:[^ "]+/<ARN>/g' \
    -e 's/ip-[0-9]+-[0-9]+-[0-9]+-[0-9]+\.[a-z0-9.-]+/<NODE>/g' \
    -e 's/\bi-[0-9a-f]{8,17}\b/<INSTANCE>/g'
}

k() { kubectl -n "$namespace" "$@" 2>&1 | mask; }

sample() {
  echo "::group::rollout sample $(date -u +%H:%M:%S)"
  k get pods -o wide
  echo "--- target group bindings"
  k get targetgroupbindings
  echo "--- newest events"
  k get events --sort-by=.lastTimestamp | tail -n 15
  # For each pod that is not Ready: why, and the last lines of what it said.
  local pod
  for pod in $(kubectl -n "$namespace" get pods --no-headers 2>/dev/null \
      | awk '{split($2, r, "/"); if (r[1] != r[2] || $3 != "Running") print $1}' | head -n 4); do
    echo "--- $pod"
    k get pod "$pod" -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}{"\n"}{end}'
    k get pod "$pod" -o jsonpath='{range .status.containerStatuses[*]}{.name}: ready={.ready} restarts={.restartCount} state={.state}{"\n"}{end}'
    k logs "$pod" --all-containers --tail=15
  done
  echo "::endgroup::"
}

while true; do
  sample
  sleep "$interval"
done
