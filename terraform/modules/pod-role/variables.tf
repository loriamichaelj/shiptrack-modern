variable "name" {
  description = "Full IAM role name, <PREFIX>-modern-<workload>."
  type        = string
}

variable "description" {
  description = "What the role is for."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "The platform workload boundary. Every role carries it."
  type        = string
}

variable "cluster_name" {
  description = "EKS cluster the Pod Identity association belongs to."
  type        = string
}

variable "namespace" {
  description = "Namespace of the service account."
  type        = string
}

variable "service_account" {
  description = "Service account that assumes the role."
  type        = string
}

variable "attach_inline_policy" {
  description = "Whether policy_json is attached. A separate flag because policy_json is unknown until apply, and count cannot depend on that."
  type        = bool
  default     = true
}

variable "policy_json" {
  description = "Inline policy document, resource-scoped. Ignored when attach_inline_policy is false."
  type        = string
  default     = null
}

variable "managed_policy_arns" {
  description = "AWS managed policies to attach."
  type        = list(string)
  default     = []
}

variable "create_association" {
  description = "Create the Pod Identity association. Turn off when the EKS add-on creates it."
  type        = bool
  default     = true
}
