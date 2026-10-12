# --- Grafana (design 8.2, 11.2) ------------------------------------------------------------------
# A ClusterIP service with no Kubernetes ingress. A TargetGroupBinding registers its pods in the
# platform's tg-grafana, behind the ALB listener on port 3000 that only the preview addresses can
# reach (platform ADR-0035, modern ADR-0027); `kubectl port-forward` still works for an operator who
# has cluster access. The datasource is the Amazon Managed Prometheus workspace, signed with SigV4
# using the pod's Pod Identity role. The dashboards are the JSON files in observability/grafana,
# provisioned from a ConfigMap, so nothing is edited by hand.

locals {
  grafana_namespace = local.service_accounts["grafana"].namespace
  dashboards        = fileset("${path.module}/../../observability/grafana", "*.json")
  amp_url           = "https://aps-workspaces.${local.region}.amazonaws.com/workspaces/${local.modern.amp_workspace_id}/"

  # The container's port; the chart's service maps 80 to it.
  grafana_container_port = 3000
  dashboards_path        = "/var/lib/grafana/dashboards/shiptrack"
}

resource "kubernetes_namespace_v1" "monitoring" {
  metadata {
    name = local.grafana_namespace

    labels = {
      "pod-security.kubernetes.io/enforce" = "baseline"
      "pod-security.kubernetes.io/warn"    = "restricted"
    }
  }
}

resource "kubernetes_config_map_v1" "dashboards" {
  metadata {
    name      = "shiptrack-dashboards"
    namespace = kubernetes_namespace_v1.monitoring.metadata[0].name
  }

  data = { for f in local.dashboards : f => file("${path.module}/../../observability/grafana/${f}") }
}

resource "helm_release" "grafana" {
  name       = "grafana"
  namespace  = kubernetes_namespace_v1.monitoring.metadata[0].name
  repository = "https://grafana.github.io/helm-charts"
  chart      = "grafana"
  version    = var.grafana_chart_version

  atomic          = true
  cleanup_on_fail = true
  timeout         = 600

  values = [yamlencode({
    serviceAccount = {
      create = true
      name   = local.service_accounts["grafana"].name
    }

    service = { type = "ClusterIP" }

    persistence = { enabled = false }

    # Everyone who reaches the port is an allow-listed address, so there is no login: anonymous
    # users are read-only viewers. The admin password stays the chart's random one and is unused.
    # viewers_can_edit also lets a viewer open Explore, the query UI for the managed Prometheus; the
    # provisioned dashboards cannot be saved over (editable = false, disableDeletion).
    "grafana.ini" = {
      "auth.anonymous" = {
        enabled  = true
        org_role = "Viewer"
      }
      users = {
        viewers_can_edit = true
        default_theme    = "dark"
      }
      dashboards = {
        default_home_dashboard_path = "${local.dashboards_path}/traffic.json"
        min_refresh_interval        = "5s"
      }
      security = { disable_gravatar = true }
      analytics = {
        reporting_enabled        = false
        check_for_updates        = false
        check_for_plugin_updates = false
      }
      news = { news_feed_enabled = false }
    }

    # The binding that puts the pods behind the platform's tg-grafana. The ALB's security group may
    # reach the container port; the load balancer controller adds that rule.
    extraObjects = [{
      apiVersion = "elbv2.k8s.aws/v1beta1"
      kind       = "TargetGroupBinding"
      metadata   = { name = "grafana", namespace = local.grafana_namespace }
      spec = {
        serviceRef     = { name = "grafana", port = 80 }
        targetGroupARN = local.platform.tg_grafana_arn
        targetType     = "ip"
        networking = {
          ingress = [{
            from  = [{ securityGroup = { groupID = local.platform.sg_alb_id } }]
            ports = [{ protocol = "TCP", port = local.grafana_container_port }]
          }]
        }
      }
    }]

    resources = {
      requests = { cpu = "100m", memory = "192Mi" }
      limits   = { memory = "384Mi" }
    }

    datasources = {
      "datasources.yaml" = {
        apiVersion = 1
        datasources = [{
          name      = "AMP"
          type      = "prometheus"
          access    = "proxy"
          uid       = "amp"
          url       = local.amp_url
          isDefault = true
          jsonData = {
            httpMethod    = "POST"
            sigV4Auth     = true
            sigV4AuthType = "default"
            sigV4Region   = local.region
            # The scraper's interval, so $__rate_interval is four scrapes (the managed collector
            # accepts nothing under 30 s).
            timeInterval = "30s"
          }
        }]
      }
    }

    dashboardProviders = {
      "dashboardproviders.yaml" = {
        apiVersion = 1
        providers = [{
          name            = "shiptrack"
          orgId           = 1
          folder          = "ShipTrack"
          type            = "file"
          disableDeletion = true
          editable        = false
          options         = { path = local.dashboards_path }
        }]
      }
    }

    dashboardsConfigMaps = { shiptrack = kubernetes_config_map_v1.dashboards.metadata[0].name }
  })]
}
