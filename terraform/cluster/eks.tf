# --- The cluster (design 8.1) --------------------------------------------------------------------

module "eks" {
  #checkov:skip=CKV_TF_1: the module comes from the Terraform registry at a pinned major (~> 21.0) and its provider lock records the checksums; a commit-hash source would bypass the registry
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name                = local.cluster_name
  kubernetes_version  = var.kubernetes_version
  deletion_protection = true

  vpc_id     = local.platform.vpc_id
  subnet_ids = local.subnet_ids

  # Access entries only; the aws-auth ConfigMap is not used.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = false

  endpoint_private_access      = true
  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.eks_public_cidrs

  # Secrets envelope encryption with this cluster's own key, alias/shiptrack-eks.
  create_kms_key          = true
  kms_key_aliases         = ["shiptrack-eks"]
  enable_kms_key_rotation = true
  encryption_config       = { resources = ["secrets"] }

  enabled_log_types                      = ["api", "audit", "authenticator"]
  cloudwatch_log_group_retention_in_days = 14
  cloudwatch_log_group_kms_key_id        = local.platform.kms_logs_key_arn

  iam_role_name                 = local.role_name["cluster"]
  iam_role_use_name_prefix      = false
  iam_role_permissions_boundary = local.platform.permission_boundary_arn

  # The customer managed policy that lets the cluster role use the secrets key.
  encryption_policy_name            = "${var.role_prefix}-modern-eks-encryption"
  encryption_policy_use_name_prefix = false

  node_iam_role_name                 = local.role_name["node"]
  node_iam_role_use_name_prefix      = false
  node_iam_role_permissions_boundary = local.platform.permission_boundary_arn

  access_entries = merge(
    {
      for arn in var.admin_role_arns : "admin-${md5(arn)}" => {
        principal_arn = arn
        policy_associations = {
          admin = {
            policy_arn   = "arn:${local.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    },
    {
      # The addons root installs controllers and cluster-scoped objects, so apply is cluster admin.
      apply = {
        principal_arn = local.pipeline_role_arn["apply"]
        policy_associations = {
          admin = {
            policy_arn   = "arn:${local.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
      plan = {
        principal_arn = local.pipeline_role_arn["plan"]
        policy_associations = {
          view = {
            policy_arn   = "arn:${local.partition}:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
      # Deploy has no access policy: the group is bound to a namespace Role by the addons root.
      deploy = {
        principal_arn     = local.pipeline_role_arn["deploy"]
        kubernetes_groups = ["shiptrack-deployers"]
      }
    },
  )

  addons = {
    eks-pod-identity-agent = {
      before_compute = true
      addon_version  = lookup(var.addon_versions, "eks-pod-identity-agent", null)
      most_recent    = !contains(keys(var.addon_versions), "eks-pod-identity-agent")
    }
    vpc-cni = {
      before_compute = true
      addon_version  = lookup(var.addon_versions, "vpc-cni", null)
      most_recent    = !contains(keys(var.addon_versions), "vpc-cni")
      configuration_values = jsonencode({
        enableNetworkPolicy = "true"
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    kube-proxy = {
      addon_version = lookup(var.addon_versions, "kube-proxy", null)
      most_recent   = !contains(keys(var.addon_versions), "kube-proxy")
    }
    coredns = {
      addon_version = lookup(var.addon_versions, "coredns", null)
      most_recent   = !contains(keys(var.addon_versions), "coredns")
    }
    metrics-server = {
      addon_version = lookup(var.addon_versions, "metrics-server", null)
      most_recent   = !contains(keys(var.addon_versions), "metrics-server")
    }
    amazon-cloudwatch-observability = {
      addon_version = lookup(var.addon_versions, "amazon-cloudwatch-observability", null)
      most_recent   = !contains(keys(var.addon_versions), "amazon-cloudwatch-observability")
      pod_identity_association = [{
        role_arn        = module.cwagent_role.arn
        service_account = local.service_accounts["cwagent"].name
      }]
    }
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = [var.node_instance_type]
      capacity_type  = "ON_DEMAND"
      min_size       = var.node_min_size
      max_size       = var.node_max_size
      desired_size   = var.node_desired_size

      subnet_ids = local.subnet_ids

      # Node-level database access: every pod on the node can reach RDS. Security Groups for Pods
      # would be stricter (ADR-0008).
      vpc_security_group_ids = [local.platform.sg_db_client_id]

      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required"
        http_put_response_hop_limit = 1
      }

      block_device_mappings = {
        root = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 40
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }

      update_config = { max_unavailable = 1 }
    }
  }
}
