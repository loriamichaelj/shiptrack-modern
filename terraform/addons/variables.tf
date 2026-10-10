variable "aws_region" {
  description = "Region of the cluster."
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

variable "lbc_chart_version" {
  description = "Version of the aws-load-balancer-controller chart (app v3.6.0). The IAM policy vendored in terraform/cluster/policies/lbc.json must be from the same release."
  type        = string
  default     = "3.6.0"
}

variable "keda_chart_version" {
  description = "Version of the keda chart."
  type        = string
  default     = "2.21.0"
}

variable "grafana_chart_version" {
  description = "Version of the grafana chart."
  type        = string
  default     = "10.5.15"
}
