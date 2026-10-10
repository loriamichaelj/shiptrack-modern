variable "aws_region" {
  description = "Region of every resource in this root."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name; it is also the Environment tag."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Owner tag. The workflows supply the repository owner (TF_VAR_owner)."
  type        = string

  validation {
    condition     = length(var.owner) > 0
    error_message = "owner must not be empty."
  }
}

variable "cost_center" {
  description = "CostCenter tag."
  type        = string
}

variable "role_prefix" {
  description = "Prefix of every IAM role and policy name: <owner>-<environment>-<project>. The workflows supply it from the ROLE_PREFIX repository variable (TF_VAR_role_prefix)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$", var.role_prefix))
    error_message = "role_prefix must be 2 to 40 characters: lowercase letters, digits, and hyphens."
  }
}

variable "kubernetes_version" {
  description = "EKS control-plane version. Standard support for 1.36 ends 2027-08-02; extended support costs about six times as much per cluster-hour."
  type        = string
  default     = "1.36"
}

variable "admin_role_arns" {
  description = "IAM roles (humans) that get cluster-admin access entries."
  type        = list(string)
  default     = []
}

variable "eks_public_cidrs" {
  description = "CIDRs allowed to reach the public API endpoint. The default is open because GitHub-hosted runners have no stable addresses (risk M-R1); the private endpoint is always on."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "node_instance_type" {
  description = "Instance type of the system node group (arm64)."
  type        = string
  default     = "m7g.large"
}

variable "node_min_size" {
  description = "Smallest size of the system node group."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Largest size of the system node group."
  type        = number
  default     = 3
}

variable "node_desired_size" {
  description = "Initial size of the system node group; the autoscaler of record owns it afterwards."
  type        = number
  default     = 2
}

variable "addon_versions" {
  description = "Pinned versions of the EKS managed add-ons, by add-on name. An add-on left out resolves to the newest version compatible with kubernetes_version when it is first created; record what it resolved to here (the addon_versions output) so later plans are stable."
  type        = map(string)
  default     = {}
}

variable "enable_amp_scraper" {
  description = "Create the agentless Prometheus scraper. It needs the cluster to be reachable, so it can be turned off for a first apply that must not wait on it."
  type        = bool
  default     = true
}
