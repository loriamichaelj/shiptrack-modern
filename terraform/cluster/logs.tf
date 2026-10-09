# --- Container Insights log groups (design 13, O-M5) ---------------------------------------------
# The add-on creates these on first write, with no expiry and no key. Creating them first gives the
# groups the platform logs key and 14 days of retention, and gives the metric filters below a group
# to attach to.

resource "aws_cloudwatch_log_group" "insights" {
  #checkov:skip=CKV_AWS_338: Container Insights logs are kept 14 days to limit cost (design 13, O-M5)
  for_each = toset(["application", "performance", "dataplane", "host"])

  name              = "/aws/containerinsights/${local.cluster_name}/${each.key}"
  retention_in_days = 14
  kms_key_id        = local.platform.kms_logs_key_arn
}
