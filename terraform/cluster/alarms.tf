# --- Alarms owned by this stack (design 8.1, 11.1) -----------------------------------------------
# They notify the platform's SNS topics. Missing data means "no problem" except for the SLA-scan
# heartbeat, whose silence is the problem.

locals {
  sev1 = [local.platform.sns_sev1_arn]
  sev2 = [local.platform.sns_sev2_arn]

  queues = {
    events        = aws_sqs_queue.events.name
    notifications = aws_sqs_queue.notifications.name
  }
  dlqs = {
    events        = aws_sqs_queue.events_dlq.name
    notifications = aws_sqs_queue.notifications_dlq.name
  }
}

resource "aws_cloudwatch_metric_alarm" "events_queue_age" {
  alarm_name          = "shiptrack-modern-events-queue-age"
  alarm_description   = "SEV2: the oldest event has waited more than 2 minutes. The workers are behind or stopped."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = local.queues["events"] }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 5
  threshold           = 120
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.sev2
  ok_actions          = local.sev2
}

resource "aws_cloudwatch_metric_alarm" "events_queue_age_critical" {
  alarm_name          = "shiptrack-modern-events-queue-age-critical"
  alarm_description   = "SEV1: the oldest event has waited more than 10 minutes."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = local.queues["events"] }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 5
  threshold           = 600
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.sev1
  ok_actions          = local.sev1
}

resource "aws_cloudwatch_metric_alarm" "dlq_visible" {
  for_each = local.dlqs

  alarm_name          = "shiptrack-modern-${each.key}-dlq-visible"
  alarm_description   = "SEV2: a message is in the ${each.key} dead-letter queue. Look at it before the 14-day retention ends."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.sev2
  ok_actions          = local.sev2
}

# Container Insights publishes pod_number_of_container_restarts only per pod, so no fixed set of
# dimensions can alarm on the namespace as a whole. The performance log events carry the same
# counter; the filter publishes the largest one in the namespace and the alarm watches its growth.
resource "aws_cloudwatch_log_metric_filter" "pod_restarts" {
  name           = "shiptrack-modern-pod-restarts"
  log_group_name = aws_cloudwatch_log_group.insights["performance"].name
  pattern        = "{ $.Type = \"Pod\" && $.Namespace = \"${local.namespace}\" && $.pod_number_of_container_restarts = * }"

  metric_transformation {
    name          = "PodContainerRestarts"
    namespace     = "ShipTrack/Modern"
    value         = "$.pod_number_of_container_restarts"
    default_value = null
  }
}

resource "aws_cloudwatch_metric_alarm" "pod_restarts" {
  alarm_name          = "shiptrack-modern-pod-restarts"
  alarm_description   = "SEV2: containers in the shiptrack namespace restarted more than 3 times in 10 minutes."
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.sev2
  ok_actions          = local.sev2

  metric_query {
    id          = "growth"
    expression  = "RATE(restarts) * 600"
    label       = "Restarts in 10 minutes"
    return_data = true
  }

  metric_query {
    id = "restarts"

    metric {
      namespace   = "ShipTrack/Modern"
      metric_name = aws_cloudwatch_log_metric_filter.pod_restarts.metric_transformation[0].name
      period      = 600
      stat        = "Maximum"
    }
  }
}

# The SLA scan logs sla_scan_completed after each run. The CronJob stays suspended until Wave 3, so
# the alarm is created with its actions off and is turned on then.
resource "aws_cloudwatch_log_metric_filter" "sla_scan" {
  name           = "shiptrack-modern-sla-scan-completed"
  log_group_name = aws_cloudwatch_log_group.insights["application"].name
  pattern        = "{ $.event = \"sla_scan_completed\" }"

  metric_transformation {
    name          = "SlaScanCompleted"
    namespace     = "ShipTrack/Modern"
    value         = "1"
    default_value = null
  }
}

resource "aws_cloudwatch_metric_alarm" "sla_scan_heartbeat" {
  #checkov:skip=CKV_AWS_319: created with actions off until the modern CronJob takes over in Wave 3 (design 8.1)
  alarm_name          = "shiptrack-modern-sla-scan-heartbeat"
  alarm_description   = "SEV2: no SLA scan has completed in 15 minutes. Enabled when the modern CronJob takes over (Wave 3)."
  namespace           = "ShipTrack/Modern"
  metric_name         = aws_cloudwatch_log_metric_filter.sla_scan.metric_transformation[0].name
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = false
  alarm_actions       = local.sev2
}

# --- Availability SLO burn rate (design 11.1) ----------------------------------------------------
# Error budget 0.5%. Burn rate = (5xx / requests) / 0.005. Each severity pairs a long and a short
# window so that a page needs both a sustained burn and one that is still happening.

locals {
  # The CloudWatch dimension values are the ARN suffixes: "targetgroup/..." and "app/...".
  tg_suffix  = regex("targetgroup/.+$", local.platform.tg_modern_arn)
  alb_suffix = regex("loadbalancer/(.+)$", local.platform.alb_arn)[0]

  burn_windows = {
    fast-long  = { period = 3600, periods = 1, threshold = 14.4 }
    fast-short = { period = 300, periods = 1, threshold = 14.4 }
    slow-long  = { period = 3600, periods = 6, threshold = 6 }
    slow-short = { period = 300, periods = 6, threshold = 6 }
  }
}

resource "aws_cloudwatch_metric_alarm" "burn" {
  for_each = local.burn_windows

  alarm_name          = "shiptrack-modern-availability-burn-${each.key}"
  alarm_description   = "Window of the availability burn-rate alarm; it does not notify on its own."
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "burn"
    expression  = "IF(requests > 0, FILL(errors, 0) / requests / 0.005, 0)"
    label       = "Error budget burn rate"
    return_data = true
  }

  metric_query {
    id = "errors"

    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      period      = each.value.period
      stat        = "Sum"
      dimensions = {
        TargetGroup  = local.tg_suffix
        LoadBalancer = local.alb_suffix
      }
    }
  }

  metric_query {
    id = "requests"

    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      period      = each.value.period
      stat        = "Sum"
      dimensions = {
        TargetGroup  = local.tg_suffix
        LoadBalancer = local.alb_suffix
      }
    }
  }
}

resource "aws_cloudwatch_composite_alarm" "slo_availability_fast_burn" {
  alarm_name        = "shiptrack-modern-slo-availability-fast-burn"
  alarm_description = "SEV1: the availability error budget burns at more than 14.4x over 1 hour and over 5 minutes."
  alarm_rule        = "ALARM(\"${aws_cloudwatch_metric_alarm.burn["fast-long"].alarm_name}\") AND ALARM(\"${aws_cloudwatch_metric_alarm.burn["fast-short"].alarm_name}\")"
  alarm_actions     = local.sev1
  ok_actions        = local.sev1
}

resource "aws_cloudwatch_composite_alarm" "slo_availability_slow_burn" {
  alarm_name        = "shiptrack-modern-slo-availability-slow-burn"
  alarm_description = "SEV2: the availability error budget burns at more than 6x over 6 hours and over 30 minutes."
  alarm_rule        = "ALARM(\"${aws_cloudwatch_metric_alarm.burn["slow-long"].alarm_name}\") AND ALARM(\"${aws_cloudwatch_metric_alarm.burn["slow-short"].alarm_name}\")"
  alarm_actions     = local.sev2
  ok_actions        = local.sev2
}
