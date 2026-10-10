output "namespace" {
  description = "The application namespace the chart installs into."
  value       = kubernetes_namespace_v1.shiptrack.metadata[0].name
}

output "grafana_port_forward" {
  description = "How to reach Grafana; it has no ingress."
  value       = "kubectl -n ${local.grafana_namespace} port-forward svc/grafana 3000:80"
}
