# --- Grafana (design 8.2, 11.2) ------------------------------------------------------------------
# ClusterIP only: it is reached with `kubectl port-forward`. The datasource is the Amazon Managed
# Prometheus workspace, signed with SigV4 using the pod's Pod Identity role. The dashboards are the
# JSON files in observability/grafana, provisioned from a ConfigMap, so nothing is edited by hand.

locals {
  grafana_namespace = local.service_accounts["grafana"].namespace
  dashboards        = fileset("${path.module}/../../observability/grafana", "*.json")
  amp_url           = "https://aps-workspaces.${local.region}.amazonaws.com/workspaces/${local.modern.amp_workspace_id}/"
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
          url       = local.amp_url
          isDefault = true
          jsonData = {
            httpMethod    = "POST"
            sigV4Auth     = true
            sigV4AuthType = "default"
            sigV4Region   = local.region
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
          options         = { path = "/var/lib/grafana/dashboards/shiptrack" }
        }]
      }
    }

    dashboardsConfigMaps = { shiptrack = kubernetes_config_map_v1.dashboards.metadata[0].name }
  })]
}
