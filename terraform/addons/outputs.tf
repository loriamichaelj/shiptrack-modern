output "namespace" {
  description = "The application namespace the chart installs into."
  value       = kubernetes_namespace_v1.shiptrack.metadata[0].name
}

output "grafana_port_forward" {
  description = "How an operator with cluster access reaches Grafana. Everyone else uses the ALB's Grafana port from an allow-listed address."
  value       = "kubectl -n ${local.grafana_namespace} port-forward svc/grafana 3000:80"
}
