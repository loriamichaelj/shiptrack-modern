#!/usr/bin/env bash
# Exercise .github/scripts/terraform-destroy.sh against a fake `aws` and a fake `terraform`: the
# confirmation check, the order of the steps in each mode, the state key of each root, and the guard
# that refuses to apply a plan that would create the protected resources again. Needs jq. Nothing
# contacts AWS.
# Usage: tests/workflows/test_terraform_destroy.sh
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
script="$repo/.github/scripts/terraform-destroy.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }
ok() { if "${@:2}"; then pass "$1"; else fail "$1"; fi; }
not() { ! "$@"; }
check() { if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1: expected [$3] got [$2]"; fi; }

mkdir -p "$work/bin"
cat >"$work/bin/aws" <<'FAKE'
#!/usr/bin/env bash
echo "123456789012"
FAKE
cat >"$work/bin/terraform" <<'FAKE'
#!/usr/bin/env bash
# Records each call; `show` prints a plan with one update, or one create when FAKE_CREATES is set.
printf '%s\n' "$*" >>"$FAKE_DIR/calls"
if [[ "$1" == show ]]; then
  action=update
  [[ -z "${FAKE_CREATES:-}" || "$3" != unprotect.tfplan ]] || action=create
  printf '{"resource_changes":[{"address":"aws_ecr_repository.app","change":{"actions":["%s"]}}]}\n' "$action"
fi
FAKE
chmod +x "$work/bin/aws" "$work/bin/terraform"

# run <root> <mode> <confirm>: output in $work/out, calls in $work/calls
run() {
  : >"$work/calls"
  PATH="$work/bin:$PATH" FAKE_DIR="$work" AWS_REGION=us-east-1 CONFIRM="$3" \
    UNPROTECT_VARS="${UNPROTECT_VARS:-}" UNPROTECT_TARGETS="${UNPROTECT_TARGETS:-}" \
    "$script" "$1" "$2" all >"$work/out" 2>&1
}
protect() {
  export UNPROTECT_VARS="eks_deletion_protection=false ecr_force_delete=true"
  export UNPROTECT_TARGETS="module.eks.aws_eks_cluster.this[0] aws_ecr_repository.app"
}

echo "terraform-destroy.sh"

status=0
run cluster destroy nope || status=$?
check "a wrong confirmation fails" "$status" "1"
check "a wrong confirmation runs no terraform" "$(wc -l <"$work/calls" | tr -d ' ')" "0"

status=0
run nowhere plan all || status=$?
check "an unknown root fails" "$status" "2"

run addons plan all
ok "addons: the state key is the addons root's" grep -q -- '-backend-config=key=modern/addons/dev.tfstate' "$work/calls"
check "addons plan: init, one destroy plan, no apply" \
  "$(grep -c '^init \|^plan -destroy ' "$work/calls") $(grep -c '^apply' "$work/calls")" "2 0"

run addons destroy all
check "addons destroy with no protection: one apply" "$(grep -c '^apply' "$work/calls")" "1"

protect
run cluster plan all
ok "cluster: the state key is the cluster root's" grep -q -- '-backend-config=key=modern/cluster/dev.tfstate' "$work/calls"
check "cluster plan: no apply and no targeted plan" \
  "$(grep -c '^apply' "$work/calls") $(grep -c -- '-target=' "$work/calls")" "0 0"

run cluster destroy all
check "cluster destroy: two applies" "$(grep -c '^apply' "$work/calls")" "2"
ok "cluster destroy: the targets are named" grep -q -- '-target=module.eks.aws_eks_cluster.this\[0\] -target=aws_ecr_repository.app' "$work/calls"
first=$(grep -n -- '-target=' "$work/calls" | head -1 | cut -d: -f1)
last=$(grep -n '^plan -destroy' "$work/calls" | head -1 | cut -d: -f1)
ok "cluster destroy: the protection is lowered before the destroy plan" test "${first:-9}" -lt "${last:-0}"
ok "cluster destroy: the destroy plan keeps the variables" grep -q -- '^plan -destroy .*-var eks_deletion_protection=false -var ecr_force_delete=true' "$work/calls"
ok "cluster destroy: reports completion" grep -q 'Destroy complete' "$work/out"

FAKE_CREATES=1 run cluster destroy all
check "cluster destroy: a plan that would create the targets is not applied" "$(grep -c '^apply' "$work/calls")" "1"
ok "cluster destroy: says why it skipped" grep -q 'Not applying it' "$work/out"

status=0
UNPROTECT_VARS="eks_deletion_protection=false" UNPROTECT_TARGETS="" run cluster destroy all || status=$?
check "variables without targets are refused" "$status" "2"
status=0
UNPROTECT_VARS="x=\$(id)" UNPROTECT_TARGETS="a" run cluster destroy all || status=$?
check "a malformed assignment is refused" "$status" "2"

ok "the account ID is masked, not printed" test "$(grep -v '^::add-mask::' "$work/out" | grep -c '123456789012' || true)" = 0

if ((failures > 0)); then
  printf '%d failure(s)\n' "$failures"
  exit 1
fi
echo "all passed"
