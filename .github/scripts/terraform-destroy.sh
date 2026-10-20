#!/usr/bin/env bash
# Take down one Terraform root (ADR-0042). Run by destroy-all.yml as <PREFIX>-modern-apply, in the dev
# environment, in two jobs that each need an approval.
# Usage: .github/scripts/terraform-destroy.sh addons|cluster plan|destroy <name>
#
# plan     shows the addresses and actions a destroy of the whole root would make.
# destroy  makes a fresh plan and applies that plan in the same run; no plan file leaves the runner.
#
# Both modes fail unless the CONFIRM environment variable equals <name>. As in terraform-ci.sh, only
# addresses and actions are printed, and a failure prints Terraform's output with identifiers masked.
#
# A protected resource (the cluster, the image repository) cannot be destroyed while its protection is
# on, and the provider reads the stored value when it deletes. When UNPROTECT_VARS lists assignments,
# `destroy` first applies the addresses in UNPROTECT_TARGETS with those variables set, then destroys
# with them still set. The next normal apply sets the protection back for anything that remains.
#
# Environment:
#   CONFIRM           the value the person typed; must equal <name> (required)
#   AWS_REGION        region of the state bucket (required)
#   UNPROTECT_VARS    optional; variable assignments, separated by spaces, such as eks_deletion_protection=false
#   UNPROTECT_TARGETS addresses, separated by spaces, that the unprotecting step applies (required with UNPROTECT_VARS)
#   TF_VAR_*          input variables
set -euo pipefail

root=${1:?usage: terraform-destroy.sh addons|cluster plan|destroy <name>}
mode=${2:?usage: terraform-destroy.sh addons|cluster plan|destroy <name>}
name=${3:?usage: terraform-destroy.sh addons|cluster plan|destroy <name>}
[[ "$root" == addons || "$root" == cluster ]] || { echo "unknown root: $root" >&2; exit 2; }
[[ "$mode" == plan || "$mode" == destroy ]] || { echo "unknown mode: $mode" >&2; exit 2; }
: "${AWS_REGION:?AWS_REGION is required}"

if [[ "${CONFIRM:-}" != "$name" ]]; then
  echo "::error::The confirmation does not match. Type ${name} to take it down."
  exit 1
fi
export TF_IN_AUTOMATION=1 TF_INPUT=0

state_key="modern/${root}/dev.tfstate"
cd "$(dirname "${BASH_SOURCE[0]}")/../../terraform/${root}"

account=$(aws sts get-caller-identity --query Account --output text)
echo "::add-mask::$account"
bucket="shiptrack-tfstate-${account}-${AWS_REGION}"

log() { printf '%s\n' "$*"; }

# Run a terraform command quietly; show its output only if it fails, with identifiers masked.
quietly() {
  local out
  out=$(mktemp)
  if ! "$@" >"$out" 2>&1; then
    sed -E "s/${account}/***/g; s/\[id=[^]]*\]/[id=***]/g; s/(vpc|subnet|sg|rtb|igw|eipalloc|nat|vpce|eni|acl|rtbassoc|ami|i|lt)-[0-9a-f]{8,17}/\1-***/g" "$out" >&2
    rm -f "$out"
    return 1
  fi
  rm -f "$out"
}

# summarize <plan> <step>: the addresses and actions of a saved plan, never values.
summarize() {
  local text
  text=$(terraform show -json "$1" | jq -r '
    [.resource_changes[]? | select(.change.actions != ["no-op"] and .change.actions != ["read"])] as $changes
    | (if ($changes | length) == 0 then "Nothing to change."
       else ($changes | map("- `\(.change.actions | join("+"))` \(.address)") | join("\n")) end)
      + "\n\n\($changes | length) resource change(s).\n"')
  log "$text"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '## destroy %s, %s root: %s (%s)\n\n%s\n' "$name" "$root" "$2" "$mode" "$text" >>"$GITHUB_STEP_SUMMARY"
  fi
}

unprotect=()
for assignment in ${UNPROTECT_VARS:-}; do
  [[ "$assignment" =~ ^[a-z_]+=(true|false)$ ]] || { echo "bad UNPROTECT_VARS" >&2; exit 2; }
  unprotect+=(-var "$assignment")
done
unprotect_targets=()
for address in ${UNPROTECT_TARGETS:-}; do unprotect_targets+=("-target=${address}"); done
if [[ ${#unprotect[@]} -gt 0 && ${#unprotect_targets[@]} -eq 0 ]]; then
  echo "UNPROTECT_TARGETS is required with UNPROTECT_VARS" >&2
  exit 2
fi

# The plan files stay on the runner: they are never uploaded.
quietly terraform init -input=false \
  -backend-config="bucket=${bucket}" \
  -backend-config="key=${state_key}" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="use_lockfile=true"

if [[ "$mode" == destroy && ${#unprotect[@]} -gt 0 ]]; then
  log "Lowering the protection (${UNPROTECT_VARS}) on the targets."
  quietly terraform plan -input=false -lock-timeout=120s "${unprotect_targets[@]}" "${unprotect[@]}" -out=unprotect.tfplan
  summarize unprotect.tfplan "lower the protection"
  # Lowering a protection only updates. A plan that creates something means the targets are gone, as
  # when a run that stopped part-way is dispatched again, and applying it would build them again.
  creates=$(terraform show -json unprotect.tfplan | jq '[.resource_changes[]? | select(.change.actions | index("create"))] | length')
  if ((creates > 0)); then
    log "The plan would create ${creates} resource(s): the targets are gone. Not applying it."
  else
    quietly terraform apply -input=false -lock-timeout=120s unprotect.tfplan
  fi
fi

quietly terraform plan -destroy -input=false -lock-timeout=120s ${unprotect[@]+"${unprotect[@]}"} -out=tfplan
summarize tfplan "destroy"
[[ "$mode" == destroy ]] || exit 0
quietly terraform apply -input=false -lock-timeout=120s tfplan
log "Destroy complete."
