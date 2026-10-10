# --- Queues and the event bus (design 5.4, 8.1) --------------------------------------------------
# Encrypted with SSE-SQS: no KMS request cost (optimization O-M8). Switch to a CMK if compliance
# requires it and record that in docs/ADR.md (ADR-0007).

resource "aws_sqs_queue" "events_dlq" {
  #checkov:skip=CKV_AWS_27: SSE-SQS is the decision recorded in ADR-0007; a CMK adds per-request KMS cost
  name                      = "shiptrack-carrier-events-dlq"
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "notifications_dlq" {
  #checkov:skip=CKV_AWS_27: SSE-SQS is the decision recorded in ADR-0007; a CMK adds per-request KMS cost
  name                      = "shiptrack-notifications-dlq"
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "events" {
  #checkov:skip=CKV_AWS_27: SSE-SQS is the decision recorded in ADR-0007; a CMK adds per-request KMS cost
  name                       = "shiptrack-carrier-events"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 4 * 24 * 3600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.events_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "notifications" {
  #checkov:skip=CKV_AWS_27: SSE-SQS is the decision recorded in ADR-0007; a CMK adds per-request KMS cost
  name                       = "shiptrack-notifications"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 4 * 24 * 3600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notifications_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "events_dlq" {
  queue_url = aws_sqs_queue.events_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.events.arn]
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "notifications_dlq" {
  queue_url = aws_sqs_queue.notifications_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.notifications.arn]
  })
}

# --- EventBridge ---------------------------------------------------------------------------------

resource "aws_cloudwatch_event_bus" "shiptrack" {
  name = "shiptrack"
}

resource "aws_cloudwatch_event_rule" "notify" {
  name           = "shiptrack-notify"
  description    = "Delivered and exception shipments go to the notifications queue."
  event_bus_name = aws_cloudwatch_event_bus.shiptrack.name

  event_pattern = jsonencode({
    source      = ["shiptrack.events"]
    detail-type = ["ShipmentDelivered", "ShipmentException"]
  })
}

resource "aws_cloudwatch_event_target" "notify" {
  rule           = aws_cloudwatch_event_rule.notify.name
  event_bus_name = aws_cloudwatch_event_bus.shiptrack.name
  target_id      = "notifications"
  arn            = aws_sqs_queue.notifications.arn
}

data "aws_iam_policy_document" "notifications_queue" {
  statement {
    sid       = "FromTheNotifyRuleOnly"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.notifications.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.notify.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "notifications" {
  queue_url = aws_sqs_queue.notifications.id
  policy    = data.aws_iam_policy_document.notifications_queue.json
}

# Seven days of history for replay during incident recovery.
resource "aws_cloudwatch_event_archive" "shiptrack" {
  name             = "shiptrack-events"
  event_source_arn = aws_cloudwatch_event_bus.shiptrack.arn
  retention_days   = 7
}
