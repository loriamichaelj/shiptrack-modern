# --- Metrics (design 8.1) ------------------------------------------------------------------------
# Amazon Managed Service for Prometheus with the agentless scraper. The pods expose /metrics on
# port 9090 only (REM-15); the scraper keeps pods annotated prometheus.io/scrape.

resource "aws_prometheus_workspace" "shiptrack" {
  alias = "shiptrack"
}

locals {
  # The collector accepts only kubernetes_sd_config, a 30 s interval or longer, and the service
  # account token for authorization (AMP managed collector limits).
  scrape_configuration = <<-YAML
    global:
      scrape_interval: 30s
    scrape_configs:
      - job_name: shiptrack-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: "true"
          - source_labels: [__meta_kubernetes_pod_ip, __meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            regex: (.+);(.+)
            replacement: $1:$2
            target_label: __address__
          - source_labels: [__meta_kubernetes_namespace]
            target_label: namespace
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
          - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_component]
            target_label: component
  YAML
}

resource "aws_prometheus_scraper" "shiptrack" {
  count = var.enable_amp_scraper ? 1 : 0

  alias = "shiptrack"

  source {
    eks {
      cluster_arn = module.eks.cluster_arn
      subnet_ids  = local.subnet_ids
      # The node security group lets the scraper reach pods (its recommended rules allow it) and
      # reach the API server for discovery.
      security_group_ids = [module.eks.node_security_group_id]
    }
  }

  destination {
    amp {
      workspace_arn = aws_prometheus_workspace.shiptrack.arn
    }
  }

  scrape_configuration = local.scrape_configuration

  depends_on = [module.eks]
}
