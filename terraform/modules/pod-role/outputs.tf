output "arn" {
  description = "ARN of the role."
  value       = aws_iam_role.this.arn
}

output "name" {
  description = "Name of the role."
  value       = aws_iam_role.this.name
}

output "permissions_boundary" {
  description = "ARN of the boundary on the role."
  value       = aws_iam_role.this.permissions_boundary
}

output "trusted_service" {
  description = "The service principal allowed to assume the role."
  value       = one(jsondecode(data.aws_iam_policy_document.trust.json).Statement).Principal.Service
}
