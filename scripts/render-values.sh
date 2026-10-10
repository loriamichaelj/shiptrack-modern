#!/usr/bin/env bash
# Writes generated-values.yaml for the chart from the SSM contract (design 7.5).
#
#   scripts/render-values.sh [output-file]
#
# It reads /shiptrack/platform/* and /shiptrack/modern/*, which hold identifiers and ARNs, never
# secret values. The file is git-ignored; the deploy workflow generates it and passes it to Helm
# together with values-dev.yaml and the image digest.
set -euo pipefail

out="${1:-generated-values.yaml}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

read_params() {
  local path="$1"
  aws ssm get-parameters-by-path --path "$path" --region "$region" \
    --query 'Parameters[].[Name,Value]' --output text
}

declare -A p
while IFS=$'\t' read -r name value; do
  [[ -n "${name:-}" ]] && p["${name##*/}"]="$value"
done < <(read_params /shiptrack/platform/; read_params /shiptrack/modern/)

need=(vpc_cidr tg_modern_arn sg_alb_id pod_bucket_name db_app_secret_arn db_migrator_secret_arn
      base_url events_queue_url notify_queue_url event_bus_name ecr_repository_url)
for key in "${need[@]}"; do
  if [[ -z "${p[$key]:-}" ]]; then
    echo "missing SSM parameter: $key" >&2
    exit 1
  fi
done

umask 077
cat > "$out" <<YAML
region: ${region}
vpcCidr: ${p[vpc_cidr]}
baseUrl: ${p[base_url]}

image:
  repository: ${p[ecr_repository_url]}

alb:
  targetGroupArn: ${p[tg_modern_arn]}
  securityGroupId: ${p[sg_alb_id]}

aws:
  eventsQueueUrl: ${p[events_queue_url]}
  notifyQueueUrl: ${p[notify_queue_url]}
  eventBusName: ${p[event_bus_name]}
  podBucket: ${p[pod_bucket_name]}
  dbSecretArn: ${p[db_app_secret_arn]}
  dbMigratorSecretArn: ${p[db_migrator_secret_arn]}
YAML

# The values are identifiers, but they include the account ID, so keep the file out of logs.
echo "wrote ${out}"
