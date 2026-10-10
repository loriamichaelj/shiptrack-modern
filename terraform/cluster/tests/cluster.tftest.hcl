# Offline. The AWS provider skips every API call; the data sources that would make one are
# overridden. Checks what the plan shows for the root as a whole (modern design 8.1).
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "offline"
  secret_key                  = "offline"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  default_tags {
    tags = {
      Project = "shiptrack"
      Stack   = "modern"
    }
  }
}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012" }
}
override_data {
  target = module.eks.data.aws_caller_identity.current[0]
  values = { account_id = "123456789012", arn = "arn:aws:sts::123456789012:assumed-role/testowner-dev-shiptrack-modern-apply/run" }
}
override_data {
  target = module.eks.data.aws_iam_session_context.current[0]
  values = { issuer_arn = "arn:aws:iam::123456789012:role/testowner-dev-shiptrack-modern-apply" }
}
override_data {
  target = module.eks.module.kms.data.aws_caller_identity.current[0]
  values = { account_id = "123456789012" }
}
override_data {
  target = module.eks.module.eks_managed_node_group["system"].data.aws_ssm_parameter.ami[0]
  values = { value = "1.36.0-20261001" }
}
override_data {
  target = data.aws_ssm_parameter.platform["vpc_id"]
  values = { value = "vpc-mock" }
}
override_data {
  target = data.aws_ssm_parameter.platform["vpc_cidr"]
  values = { value = "10.20.0.0/16" }
}
override_data {
  target = data.aws_ssm_parameter.platform["private_app_subnet_ids"]
  values = { value = "subnet-a,subnet-b,subnet-c" }
}
override_data {
  target = data.aws_ssm_parameter.platform["sg_db_client_id"]
  values = { value = "sg-client" }
}
override_data {
  target = data.aws_ssm_parameter.platform["permission_boundary_arn"]
  values = { value = "arn:aws:iam::123456789012:policy/testowner-dev-shiptrack-workload-boundary" }
}
override_data {
  target = data.aws_ssm_parameter.platform["kms_data_key_arn"]
  values = { value = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-00000000000a" }
}
override_data {
  target = data.aws_ssm_parameter.platform["kms_secrets_key_arn"]
  values = { value = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-00000000000b" }
}
override_data {
  target = data.aws_ssm_parameter.platform["kms_logs_key_arn"]
  values = { value = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-00000000000c" }
}
override_data {
  target = data.aws_ssm_parameter.platform["pod_bucket_arn"]
  values = { value = "arn:aws:s3:::shiptrack-pod-123456789012-us-east-1" }
}
override_data {
  target = data.aws_ssm_parameter.platform["db_app_secret_arn"]
  values = { value = "arn:aws:secretsmanager:us-east-1:123456789012:secret:shiptrack/dev/db/app-AbCdEf" }
}
override_data {
  target = data.aws_ssm_parameter.platform["db_migrator_secret_arn"]
  values = { value = "arn:aws:secretsmanager:us-east-1:123456789012:secret:shiptrack/dev/db/migrator-AbCdEf" }
}
override_data {
  target = data.aws_ssm_parameter.platform["sns_sev1_arn"]
  values = { value = "arn:aws:sns:us-east-1:123456789012:shiptrack-alerts-sev1" }
}
override_data {
  target = data.aws_ssm_parameter.platform["sns_sev2_arn"]
  values = { value = "arn:aws:sns:us-east-1:123456789012:shiptrack-alerts-sev2" }
}
override_data {
  target = data.aws_ssm_parameter.platform["tg_modern_arn"]
  values = { value = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/shiptrack-tg-modern/0123456789abcdef" }
}
override_data {
  target = data.aws_ssm_parameter.platform["alb_arn"]
  values = { value = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/shiptrack-alb/0123456789abcdef" }
}
override_resource {
  target          = aws_sqs_queue.events
  override_during = plan
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:shiptrack-carrier-events"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-carrier-events"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-carrier-events"
  }
}
override_resource {
  target          = aws_sqs_queue.notifications
  override_during = plan
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:shiptrack-notifications"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-notifications"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-notifications"
  }
}
override_resource {
  target          = aws_sqs_queue.events_dlq
  override_during = plan
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:shiptrack-carrier-events-dlq"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-carrier-events-dlq"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-carrier-events-dlq"
  }
}
override_resource {
  target          = aws_sqs_queue.notifications_dlq
  override_during = plan
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:shiptrack-notifications-dlq"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-notifications-dlq"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/shiptrack-notifications-dlq"
  }
}
override_resource {
  target          = aws_cloudwatch_event_bus.shiptrack
  override_during = plan
  values          = { arn = "arn:aws:events:us-east-1:123456789012:event-bus/shiptrack" }
}
override_resource {
  target          = aws_cloudwatch_event_rule.notify
  override_during = plan
  values          = { arn = "arn:aws:events:us-east-1:123456789012:rule/shiptrack/shiptrack-notify" }
}
override_resource {
  target          = aws_prometheus_workspace.shiptrack
  override_during = plan
  values = {
    arn = "arn:aws:aps:us-east-1:123456789012:workspace/ws-00000000-0000-0000-0000-000000000000"
    id  = "ws-00000000-0000-0000-0000-000000000000"
  }
}

variables {
  owner       = "testowner"
  cost_center = "test"
  role_prefix = "testowner-dev-shiptrack"
}

run "plan_succeeds" {
  command = plan
}

run "every_role_has_the_prefix_and_the_boundary" {
  command = plan

  assert {
    condition = alltrue([
      for k, m in module.pod_role :
      startswith(m.name, "testowner-dev-shiptrack-modern-")
    ])
    error_message = "Every Pod Identity role is named <PREFIX>-modern-<workload>."
  }

  assert {
    condition = alltrue(concat(
      [for k, m in module.pod_role : m.permissions_boundary == "arn:aws:iam::123456789012:policy/testowner-dev-shiptrack-workload-boundary"],
      [module.cwagent_role.permissions_boundary == "arn:aws:iam::123456789012:policy/testowner-dev-shiptrack-workload-boundary"],
    ))
    error_message = "Every role carries the platform workload boundary."
  }

  assert {
    condition = alltrue(concat(
      [for k, m in module.pod_role : m.trusted_service == "pods.eks.amazonaws.com"],
      [module.cwagent_role.trusted_service == "pods.eks.amazonaws.com"],
    ))
    error_message = "Only EKS Pod Identity can assume the workload roles."
  }

  assert {
    condition     = toset(keys(module.pod_role)) == toset(["api", "worker-events", "worker-notify", "sla-scan", "migrate", "lbc", "keda", "grafana"]) && module.cwagent_role.name == "testowner-dev-shiptrack-modern-cwagent"
    error_message = "One role per workload and controller, with cwagent managed by the add-on."
  }
}

run "the_service_accounts_match_the_chart" {
  command = plan

  assert {
    condition = alltrue([
      local.service_accounts["api"].name == "shiptrack-api",
      local.service_accounts["worker-events"].name == "shiptrack-worker-events",
      local.service_accounts["worker-notify"].name == "shiptrack-worker-notify",
      local.service_accounts["sla-scan"].name == "shiptrack-sla-scan",
      local.service_accounts["migrate"].name == "shiptrack-migrate",
      local.service_accounts["lbc"].namespace == "kube-system",
      local.service_accounts["keda"].namespace == "keda",
    ])
    error_message = "Pod Identity binds a role to a namespace and service account; the chart and the addons root must use these."
  }
}

run "the_cluster_follows_the_design" {
  command = plan

  assert {
    condition = alltrue([
      module.eks.cluster_name == "shiptrack",
      var.kubernetes_version == "1.36",
    ])
    error_message = "The cluster is shiptrack on Kubernetes 1.36."
  }
}

run "access_entries_grant_the_pipelines_what_they_need" {
  command = plan

  assert {
    condition = alltrue([
      contains(keys(module.eks.access_entries), "apply"),
      contains(keys(module.eks.access_entries), "plan"),
      contains(keys(module.eks.access_entries), "deploy"),
    ])
    error_message = "apply (admin), plan (view), and deploy (namespace group) each have an access entry."
  }
}

run "the_registry_is_immutable_and_encrypted" {
  command = plan

  assert {
    condition = alltrue([
      aws_ecr_repository.app.name == "shiptrack/app",
      aws_ecr_repository.app.image_tag_mutability == "IMMUTABLE",
      one(aws_ecr_repository.app.encryption_configuration).encryption_type == "KMS",
    ])
    error_message = "shiptrack/app is IMMUTABLE and KMS-encrypted."
  }
}

run "the_queues_follow_the_design" {
  command = plan

  assert {
    condition = alltrue([
      aws_sqs_queue.events.visibility_timeout_seconds == 60,
      aws_sqs_queue.events.message_retention_seconds == 345600,
      aws_sqs_queue.events.receive_wait_time_seconds == 20,
      aws_sqs_queue.events.sqs_managed_sse_enabled,
      jsondecode(aws_sqs_queue.events.redrive_policy).maxReceiveCount == 5,
      jsondecode(aws_sqs_queue.notifications.redrive_policy).maxReceiveCount == 5,
      aws_sqs_queue.events_dlq.message_retention_seconds == 1209600,
      aws_sqs_queue.notifications_dlq.message_retention_seconds == 1209600,
    ])
    error_message = "Queues: 60 s visibility, 4 d retention, long polling, SSE-SQS, redrive after 5; DLQs keep 14 d."
  }
}

run "the_bus_routes_delivered_and_exception_to_notifications" {
  command = plan

  assert {
    condition = alltrue([
      aws_cloudwatch_event_bus.shiptrack.name == "shiptrack",
      tolist(jsondecode(aws_cloudwatch_event_rule.notify.event_pattern).source) == tolist(["shiptrack.events"]),
      tolist(jsondecode(aws_cloudwatch_event_rule.notify.event_pattern)["detail-type"]) == tolist(["ShipmentDelivered", "ShipmentException"]),
      aws_cloudwatch_event_archive.shiptrack.retention_days == 7,
    ])
    error_message = "shiptrack bus, the notify rule, and a 7-day archive."
  }
}

run "the_alarms_are_wired_to_the_right_severities" {
  command = plan

  assert {
    condition = alltrue([
      aws_cloudwatch_metric_alarm.events_queue_age.threshold == 120,
      aws_cloudwatch_metric_alarm.events_queue_age_critical.threshold == 600,
      aws_cloudwatch_metric_alarm.events_queue_age.alarm_actions == toset([local.platform.sns_sev2_arn]),
      aws_cloudwatch_metric_alarm.events_queue_age_critical.alarm_actions == toset([local.platform.sns_sev1_arn]),
      toset(keys(aws_cloudwatch_metric_alarm.dlq_visible)) == toset(["events", "notifications"]),
    ])
    error_message = "Queue age warns at 2 minutes (SEV2) and pages at 10 (SEV1); both DLQs alarm on any message."
  }

  assert {
    condition = alltrue([
      aws_cloudwatch_metric_alarm.sla_scan_heartbeat.actions_enabled == false,
      aws_cloudwatch_metric_alarm.sla_scan_heartbeat.treat_missing_data == "breaching",
    ])
    error_message = "The SLA-scan heartbeat is created disabled and treats silence as a breach."
  }

  assert {
    condition = alltrue([
      aws_cloudwatch_metric_alarm.burn["fast-long"].threshold == 14.4,
      aws_cloudwatch_metric_alarm.burn["slow-long"].threshold == 6,
      try(length(aws_cloudwatch_metric_alarm.burn["fast-long"].alarm_actions) == 0, true),
    ])
    error_message = "The burn windows use 14.4x and 6x and do not notify on their own; the composites do."
  }
}

run "the_ssm_contract_has_every_key_the_chart_reads" {
  command = plan

  assert {
    condition = toset(keys(aws_ssm_parameter.contract)) == toset([
      "cluster_name", "ecr_repository_url", "events_queue_url", "events_dlq_url",
      "notify_queue_url", "notify_dlq_url", "event_bus_name", "amp_workspace_id",
    ])
    error_message = "/shiptrack/modern/ holds the eight keys from design 8.1."
  }
}
