# --- Pod Identity roles (design 7.3, 8.1) --------------------------------------------------------
# Every role is named <PREFIX>-modern-<workload>, carries the platform boundary, and is trusted by
# pods.eks.amazonaws.com only. Policies are scoped to resources this root or the platform creates.

locals {
  secrets_via = "secretsmanager.${local.region}.amazonaws.com"
  s3_via      = "s3.${local.region}.amazonaws.com"
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "SendEvents"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.events.arn]
  }

  statement {
    sid       = "PodObjects"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${local.platform.pod_bucket_arn}/pod/*"]
  }

  statement {
    sid       = "DataKeyThroughS3"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [local.platform.kms_data_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.s3_via]
    }
  }

  statement {
    sid       = "AppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.platform.db_app_secret_arn]
  }

  statement {
    sid       = "SecretsKeyThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [local.platform.kms_secrets_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.secrets_via]
    }
  }
}

data "aws_iam_policy_document" "worker_events" {
  statement {
    sid = "ConsumeEvents"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.events.arn]
  }

  statement {
    sid       = "PublishDomainEvents"
    actions   = ["events:PutEvents"]
    resources = [aws_cloudwatch_event_bus.shiptrack.arn]
  }

  statement {
    sid       = "AppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.platform.db_app_secret_arn]
  }

  statement {
    sid       = "SecretsKeyThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [local.platform.kms_secrets_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.secrets_via]
    }
  }
}

data "aws_iam_policy_document" "worker_notify" {
  statement {
    sid = "ConsumeNotifications"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.notifications.arn]
  }
}

data "aws_iam_policy_document" "sla_scan" {
  statement {
    sid       = "AppSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.platform.db_app_secret_arn]
  }

  statement {
    sid       = "SecretsKeyThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [local.platform.kms_secrets_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.secrets_via]
    }
  }
}

data "aws_iam_policy_document" "migrate" {
  statement {
    sid       = "MigratorSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.platform.db_migrator_secret_arn]
  }

  statement {
    sid       = "SecretsKeyThroughSecretsManager"
    actions   = ["kms:Decrypt"]
    resources = [local.platform.kms_secrets_key_arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.secrets_via]
    }
  }
}

data "aws_iam_policy_document" "keda" {
  statement {
    sid       = "ReadQueueDepth"
    actions   = ["sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.events.arn, aws_sqs_queue.notifications.arn]
  }
}

data "aws_iam_policy_document" "grafana" {
  statement {
    sid = "QueryMetrics"
    actions = [
      "aps:QueryMetrics",
      "aps:GetLabels",
      "aps:GetSeries",
      "aps:GetMetricMetadata",
    ]
    resources = [aws_prometheus_workspace.shiptrack.arn]
  }
}

locals {
  workload_roles = {
    api = {
      description = "ShipTrack API pods: send events, store POD objects, read the app secret."
      policy_json = data.aws_iam_policy_document.api.json
    }
    worker-events = {
      description = "ShipTrack events worker: consume the events queue, publish domain events, read the app secret."
      policy_json = data.aws_iam_policy_document.worker_events.json
    }
    worker-notify = {
      description = "ShipTrack notify worker: consume the notifications queue."
      policy_json = data.aws_iam_policy_document.worker_notify.json
    }
    sla-scan = {
      description = "ShipTrack SLA scan job: read the app secret."
      policy_json = data.aws_iam_policy_document.sla_scan.json
    }
    migrate = {
      description = "ShipTrack migration job: read the migrator secret."
      policy_json = data.aws_iam_policy_document.migrate.json
    }
    # The load balancer controller's own policy at the chart's version, vendored in policies/.
    lbc = {
      description = "AWS Load Balancer Controller."
      policy_json = file("${path.module}/policies/lbc.json")
    }
    keda = {
      description = "KEDA operator: read queue depth to scale the workers."
      policy_json = data.aws_iam_policy_document.keda.json
    }
    grafana = {
      description = "Grafana: query the Amazon Managed Prometheus workspace."
      policy_json = data.aws_iam_policy_document.grafana.json
    }
  }
}

module "pod_role" {
  source   = "../modules/pod-role"
  for_each = local.workload_roles

  name                     = local.role_name[each.key]
  description              = each.value.description
  permissions_boundary_arn = local.platform.permission_boundary_arn
  cluster_name             = module.eks.cluster_name
  namespace                = local.service_accounts[each.key].namespace
  service_account          = local.service_accounts[each.key].name
  policy_json              = each.value.policy_json
}

# The CloudWatch observability add-on creates its own association, and the add-on is part of the
# cluster module, so this role cannot depend on the cluster.
module "cwagent_role" {
  source = "../modules/pod-role"

  name                     = local.role_name["cwagent"]
  description              = "CloudWatch agent and Fluent Bit (Container Insights)."
  permissions_boundary_arn = local.platform.permission_boundary_arn
  cluster_name             = local.cluster_name
  namespace                = local.service_accounts["cwagent"].namespace
  service_account          = local.service_accounts["cwagent"].name
  attach_inline_policy     = false
  managed_policy_arns      = ["arn:${local.partition}:iam::aws:policy/CloudWatchAgentServerPolicy"]
  create_association       = false
}
