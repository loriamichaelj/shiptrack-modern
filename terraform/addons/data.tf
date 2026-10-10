data "aws_region" "current" {}

# --- What the cluster root and the platform publish ----------------------------------------------

data "aws_ssm_parameter" "modern" {
  for_each = toset(["cluster_name", "amp_workspace_id"])

  name = "/shiptrack/modern/${each.key}"
}

data "aws_ssm_parameter" "platform" {
  for_each = toset(["vpc_id"])

  name = "/shiptrack/platform/${each.key}"
}

locals {
  modern   = { for k, p in data.aws_ssm_parameter.modern : k => nonsensitive(p.value) }
  platform = { for k, p in data.aws_ssm_parameter.platform : k => nonsensitive(p.value) }

  cluster_name = local.modern.cluster_name
  region       = data.aws_region.current.region
  namespace    = "shiptrack"

  # Pod Identity binds a role to a namespace and service account. terraform/cluster creates the
  # roles and the associations; these names must match its service_accounts output.
  service_accounts = {
    lbc     = { namespace = "kube-system", name = "aws-load-balancer-controller" }
    keda    = { namespace = "keda", name = "keda-operator" }
    grafana = { namespace = "monitoring", name = "grafana" }
  }
}

data "aws_eks_cluster" "this" {
  name = local.cluster_name
}
