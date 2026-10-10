data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

# --- The platform contract -----------------------------------------------------------------------
# Read only the keys this root uses. They are identifiers and ARNs, not secrets, so the values are
# unmarked to keep plans readable.

data "aws_ssm_parameter" "platform" {
  for_each = toset([
    "vpc_id",
    "vpc_cidr",
    "private_app_subnet_ids",
    "sg_db_client_id",
    "permission_boundary_arn",
    "kms_data_key_arn",
    "kms_secrets_key_arn",
    "kms_logs_key_arn",
    "pod_bucket_arn",
    "db_app_secret_arn",
    "db_migrator_secret_arn",
    "sns_sev1_arn",
    "sns_sev2_arn",
    "tg_modern_arn",
    "alb_arn",
  ])

  name = "/shiptrack/platform/${each.key}"
}

locals {
  platform = { for k, p in data.aws_ssm_parameter.platform : k => nonsensitive(p.value) }

  account   = data.aws_caller_identity.current.account_id
  region    = data.aws_region.current.region
  partition = data.aws_partition.current.partition

  cluster_name = "shiptrack"
  namespace    = "shiptrack"
  subnet_ids   = split(",", local.platform.private_app_subnet_ids)

  # <PREFIX>-modern-<x>: the names every IAM role in this root takes (platform ADR-0011).
  role_name = { for k in [
    "api", "worker-events", "worker-notify", "sla-scan", "migrate",
    "lbc", "keda", "cwagent", "grafana",
    "cluster", "node",
  ] : k => "${var.role_prefix}-modern-${k}" }

  # The roles the platform bootstrap creates for this repository's pipelines (platform 6.1).
  pipeline_role_arn = { for k in ["apply", "plan", "deploy"] :
    k => "arn:${local.partition}:iam::${local.account}:role/${var.role_prefix}-modern-${k}"
  }

  # Names the addons root and the Helm chart must agree on. Pod Identity binds a role to a
  # namespace and service account, so these are part of the contract with them.
  service_accounts = {
    api           = { namespace = local.namespace, name = "shiptrack-api" }
    worker-events = { namespace = local.namespace, name = "shiptrack-worker-events" }
    worker-notify = { namespace = local.namespace, name = "shiptrack-worker-notify" }
    sla-scan      = { namespace = local.namespace, name = "shiptrack-sla-scan" }
    migrate       = { namespace = local.namespace, name = "shiptrack-migrate" }
    lbc           = { namespace = "kube-system", name = "aws-load-balancer-controller" }
    keda          = { namespace = "keda", name = "keda-operator" }
    cwagent       = { namespace = "amazon-cloudwatch", name = "cloudwatch-agent" }
    grafana       = { namespace = "monitoring", name = "grafana" }
  }
}
