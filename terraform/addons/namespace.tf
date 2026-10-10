# --- The application namespace (design 7.1) ------------------------------------------------------
# Terraform owns the namespace and Helm does not, so a chart rollback can never delete it.

resource "kubernetes_namespace_v1" "shiptrack" {
  metadata {
    name = local.namespace

    labels = {
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/warn"    = "restricted"
      # The load balancer controller holds a pod back from Ready until its ALB target is healthy.
      "elbv2.k8s.aws/pod-readiness-gate-inject" = "enabled"
    }
  }

  # The webhook that injects the readiness gate must be up before pods are created here.
  depends_on = [helm_release.lbc]
}

# --- What the deploy pipeline may do (design 8.2) ------------------------------------------------
# The cluster root gives <PREFIX>-modern-deploy an access entry in the group shiptrack-deployers and
# no access policy. This Role is the only thing the group can do, and only in this namespace.

resource "kubernetes_role_v1" "deployer" {
  metadata {
    name      = "shiptrack-deployer"
    namespace = kubernetes_namespace_v1.shiptrack.metadata[0].name
  }

  rule {
    api_groups = [""]
    resources  = ["pods", "services", "configmaps", "serviceaccounts", "endpoints", "persistentvolumeclaims"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods/log", "events"]
    verbs      = ["get", "list", "watch"]
  }

  # Helm keeps its release records in Secrets named sh.helm.release.v1.*; the application's own
  # credentials are not in Kubernetes at all (Secrets Manager, read by the pods).
  rule {
    api_groups = [""]
    resources  = ["secrets"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments", "replicasets"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["autoscaling"]
    resources  = ["horizontalpodautoscalers"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["policy"]
    resources  = ["poddisruptionbudgets"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["networking.k8s.io"]
    resources  = ["networkpolicies"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["batch"]
    resources  = ["jobs", "cronjobs"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["elbv2.k8s.aws"]
    resources  = ["targetgroupbindings"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = ["keda.sh"]
    resources  = ["scaledobjects", "triggerauthentications"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }
}

resource "kubernetes_role_binding_v1" "deployer" {
  metadata {
    name      = "shiptrack-deployer"
    namespace = kubernetes_namespace_v1.shiptrack.metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.deployer.metadata[0].name
  }

  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = "shiptrack-deployers"
  }
}
