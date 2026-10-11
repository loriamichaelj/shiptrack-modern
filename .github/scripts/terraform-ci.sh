#!/usr/bin/env bash
# Plan or apply one Terraform root, or print some of its outputs. Run by terraform-pr.yml,
# terraform-apply.yml, and terraform-outputs.yml.
# Usage: .github/scripts/terraform-ci.sh plan|apply|outputs
#
# The state bucket name contains the account ID, so the backend is configured at init time instead
# of being committed. A failed step prints Terraform's output with the account and resource IDs
# masked, because the logs of a public repository are public.
#
# Environment:
#   AWS_REGION        region of the state bucket (required)
#   TF_DIR            configuration directory (required): terraform/cluster or terraform/addons
#   TF_STATE_KEY      state object key (required): modern/cluster/dev.tfstate or modern/addons/dev.tfstate
#   REQUIRES_SSM      an SSM parameter that must exist, or the root is skipped (optional). The addons
#                     root reads what the cluster root publishes, so before the cluster is applied
#                     there is nothing to plan against.
#   SUMMARY_FILE      where `plan` writes the address-and-action summary as Markdown (optional)
#   PRINT_OUTPUTS     space-separated output names to print as HCL after an apply, and the outputs
#                     to print in `outputs` mode (required there). Only for outputs that hold no
#                     identifiers, such as add-on versions: the log of a public repository is public.
#   TF_VAR_*          input variables
set -euo pipefail

mode=${1:?usage: terraform-ci.sh plan|apply|outputs}
[[ "$mode" == plan || "$mode" == apply || "$mode" == outputs ]] || { echo "unknown mode: $mode" >&2; exit 2; }
: "${AWS_REGION:?AWS_REGION is required}"
: "${TF_DIR:?TF_DIR is required}"
: "${TF_STATE_KEY:?TF_STATE_KEY is required}"
export TF_IN_AUTOMATION=1 TF_INPUT=0

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
dir=$TF_DIR
cd "$dir"

account=$(aws sts get-caller-identity --query Account --output text)
echo "::add-mask::$account"
bucket="shiptrack-tfstate-${account}-${AWS_REGION}"

if [[ -n "${REQUIRES_SSM:-}" ]] && ! aws ssm get-parameter --name "$REQUIRES_SSM" >/dev/null 2>&1; then
  text="Skipped: ${REQUIRES_SSM} does not exist yet, so the cluster root has not been applied."
  echo "$text"
  [[ -z "${SUMMARY_FILE:-}" ]] || printf '%s\n' "$text" >"$SUMMARY_FILE"
  if [[ "$mode" == apply ]]; then
    echo "::error::$text"
    exit 1
  fi
  exit 0
fi

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

# Print the changes in a saved plan: addresses and actions, never attribute values. For an update it
# also names the attributes that differ, so a perpetual diff can be traced without publishing what
# changed.
summarize() {
  terraform show -json "$1" | jq -r '
    def changed($c):
      (($c.change.before // {}) as $b | ($c.change.after // {}) as $a
        | ([$b, $a] | map(keys) | add | unique)
        | map(select($b[.] != $a[.]))) | join(", ");
    [.resource_changes[]? | select(.change.actions != ["no-op"] and .change.actions != ["read"])] as $changes
    | (if ($changes | length) == 0 then "No changes."
       else ($changes | map(
              "- `\(.change.actions | join("+"))` \(.address)"
              + (if .change.actions == ["update"] then " (changed: \(changed(.)))" else "" end)
            ) | join("\n")) end)
      + "\n\n\($changes | length) resource change(s).\n"'
}

quietly terraform init -input=false \
  -backend-config="bucket=${bucket}" \
  -backend-config="key=${TF_STATE_KEY}" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="use_lockfile=true"

# Print the named outputs as HCL, ready to paste into terraform.tfvars. The account ID is masked as
# a last resort; the outputs listed in PRINT_OUTPUTS should not hold identifiers anyway.
print_outputs() {
  local name value block
  for name in ${PRINT_OUTPUTS:-}; do
    if ! value=$(terraform output -json "$name" 2>/dev/null); then
      echo "::warning::The root has no output named ${name}."
      continue
    fi
    block=$(jq -r --arg n "$name" '
        if type == "object" then
          "\($n) = {\n"
          + (to_entries | sort_by(.key) | map("  \(.key | @json) = \(.value | @json)") | join("\n"))
          + "\n}"
        else "\($n) = \(. | @json)" end' <<<"$value" | sed -E "s/${account}/***/g")
    printf '%s\n' "$block"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
      # The backticks are Markdown, not command substitution.
      # shellcheck disable=SC2016
      printf '### Output `%s`\n\n```hcl\n%s\n```\n' "$name" "$block" >>"$GITHUB_STEP_SUMMARY"
    fi
  done
}

# Read-only: no plan, no lock, nothing applied.
if [[ "$mode" == outputs ]]; then
  : "${PRINT_OUTPUTS:?PRINT_OUTPUTS is required in outputs mode}"
  print_outputs
  exit 0
fi

# The plan file stays on the runner: it is never uploaded, and apply makes its own in the same job.
plan=$(mktemp -u)
trap 'rm -f "$plan"' EXIT
quietly terraform plan -input=false -lock-timeout=120s -out="$plan"
text=$(summarize "$plan")
printf '%s\n' "$text"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf '## Terraform %s (%s)\n\n%s\n' "$mode" "$dir" "$text" >>"$GITHUB_STEP_SUMMARY"
fi
if [[ "$mode" == plan ]]; then
  [[ -z "${SUMMARY_FILE:-}" ]] || printf '%s\n' "$text" >"$SUMMARY_FILE"
  exit 0
fi

quietly terraform apply -input=false "$plan"
echo "Apply complete."
print_outputs
