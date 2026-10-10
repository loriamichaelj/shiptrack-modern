# --- Outputs and the SSM contract (design 8.1) ---------------------------------------------------
# The chart's render-values.sh and the workflows read these from /shiptrack/modern/. They are
# identifiers and ARNs, never secrets.

locals {
  contract = {
    cluster_name       = module.eks.cluster_name
    ecr_repository_url = aws_ecr_repository.app.repository_url
    events_queue_url   = aws_sqs_queue.events.url
    events_dlq_url     = aws_sqs_queue.events_dlq.url
    notify_queue_url   = aws_sqs_queue.notifications.url
    notify_dlq_url     = aws_sqs_queue.notifications_dlq.url
    event_bus_name     = aws_cloudwatch_event_bus.shiptrack.name
    amp_workspace_id   = aws_prometheus_workspace.shiptrack.id
  }
}

resource "aws_ssm_parameter" "contract" {
  #checkov:skip=CKV2_AWS_34: the contract holds identifiers and URLs, never secret values, so the parameters are plain String
  for_each = local.contract

  name  = "/shiptrack/modern/${each.key}"
  type  = "String"
  value = each.value
  tier  = "Standard"
}

output "cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "ecr_repository_url" {
  description = "Where the release workflow pushes the image."
  value       = aws_ecr_repository.app.repository_url
}

output "pod_role_arns" {
  description = "Pod Identity roles by workload."
  value       = { for k, m in module.pod_role : k => m.arn }
}

output "addon_versions" {
  description = "Versions the EKS add-ons resolved to. Copy them into addon_versions to pin them."
  value       = { for k, a in module.eks.cluster_addons : k => a.addon_version }
}

output "service_accounts" {
  description = "Namespace and name of each service account that has a Pod Identity role. The addons root and the chart must use these."
  value       = local.service_accounts
}
