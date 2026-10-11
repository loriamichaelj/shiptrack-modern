# Non-secret, non-identifying values only. The owner and the role prefix come from the workflows as
# TF_VAR_owner and TF_VAR_role_prefix; the human admin roles as TF_VAR_admin_role_arns.
aws_region  = "us-east-1"
environment = "dev"
cost_center = "shiptrack-migration"

# What each EKS add-on resolved to when it was first created (the addon_versions output, ADR-0013).
# An upgrade is a pull request that changes one value.
addon_versions = {
  "amazon-cloudwatch-observability" = "v6.7.0-eksbuild.1"
  "coredns"                         = "v1.14.7-eksbuild.11"
  "eks-pod-identity-agent"          = "v1.4.0-eksbuild.3"
  "kube-proxy"                      = "v1.36.0-eksbuild.45"
  "metrics-server"                  = "v0.9.0-eksbuild.11"
  "vpc-cni"                         = "v1.23.2-eksbuild.1"
}
