# --- Controllers (design 8.2) --------------------------------------------------------------------
# Each controller's service account has a Pod Identity association created by terraform/cluster, so
# the charts get no role annotation.

resource "helm_release" "lbc" {
  name       = "aws-load-balancer-controller"
  namespace  = local.service_accounts["lbc"].namespace
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.lbc_chart_version

  atomic          = true
  cleanup_on_fail = true
  timeout         = 600

  values = [yamlencode({
    clusterName = local.cluster_name
    region      = local.region
    vpcId       = local.platform.vpc_id

    serviceAccount = {
      create = true
      name   = local.service_accounts["lbc"].name
    }

    # Services are fronted by the platform ALB through a TargetGroupBinding, so the controller
    # needs neither the Service webhook nor the Shield and WAF integrations.
    enableServiceMutatorWebhook = false
    enableShield                = false
    enableWaf                   = false
    enableWafv2                 = false

    replicaCount = 2
    resources = {
      requests = { cpu = "100m", memory = "128Mi" }
      limits   = { memory = "256Mi" }
    }
  })]
}

resource "helm_release" "keda" {
  name             = "keda"
  namespace        = local.service_accounts["keda"].namespace
  create_namespace = true
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_chart_version

  atomic          = true
  cleanup_on_fail = true
  timeout         = 600

  values = [yamlencode({
    serviceAccount = {
      operator = {
        create = true
        name   = local.service_accounts["keda"].name
      }
    }

    resources = {
      operator = {
        requests = { cpu = "100m", memory = "128Mi" }
        limits   = { memory = "512Mi" }
      }
      metricServer = {
        requests = { cpu = "100m", memory = "128Mi" }
        limits   = { memory = "512Mi" }
      }
      webhooks = {
        requests = { cpu = "50m", memory = "64Mi" }
        limits   = { memory = "256Mi" }
      }
    }
  })]

  # KEDA's admission webhook is part of the controller set; wait for the load balancer controller's
  # so the two do not race while the cluster is coming up.
  depends_on = [helm_release.lbc]
}
