# Offline. The AWS provider skips every API call, the data sources that would make one are
# overridden, and the Kubernetes and Helm providers are only configured, never contacted: a plan
# does not need the cluster for resources that do not exist yet.
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "offline"
  secret_key                  = "offline"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

override_data {
  target = data.aws_ssm_parameter.modern["cluster_name"]
  values = { value = "shiptrack" }
}
override_data {
  target = data.aws_ssm_parameter.modern["amp_workspace_id"]
  values = { value = "ws-00000000-0000-0000-0000-000000000000" }
}
override_data {
  target = data.aws_ssm_parameter.platform["vpc_id"]
  values = { value = "vpc-mock" }
}
override_data {
  target = data.aws_eks_cluster.this
  values = {
    endpoint = "https://cluster.example.test"
    # A throwaway certificate with no key, only so the provider configuration parses.
    certificate_authority = [{ data = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUREekNDQWZlZ0F3SUJBZ0lVT2dZRXV6ai9JY0hoOHNjUGlNVzlIbXJKYlJZd0RRWUpLb1pJaHZjTkFRRUwKQlFBd0Z6RVZNQk1HQTFVRUF3d01iMlptYkdsdVpTMTBaWE4wTUI0WERUSTJNVEF3T1RFNU16STFNVm9YRFRNMgpNVEF3TmpFNU16STFNVm93RnpFVk1CTUdBMVVFQXd3TWIyWm1iR2x1WlMxMFpYTjBNSUlCSWpBTkJna3Foa2lHCjl3MEJBUUVGQUFPQ0FROEFNSUlCQ2dLQ0FRRUE4MmhwS3JIWHFJdDl4S1V2TEwycWdXUlhiQkJNbTRFNnlvUTkKTHNCNnJzM1pYbzhQWCs2dkFVc2RyaVJrNU0xMG5FTldKRTdsdkZGYXk1YVAyUzcxS0VXWjE0WjQyQ0d6dkMxeApDbW1sdkpVRGFITDdLUTZIYnNldUtGV2RJR3ZNM0MwYUIwalZ2NkFLWDNCVS9BSHMydjVrVHJ6UFByQ003YzdPCkFtL3ZFK2xwaDJaeWtVenl1OTk1ZHdDd0trN2VzNDhRMGRMSXpndDIzOVhweTRYMzdZeGR2VDVwTG5yT21vMlcKMENHelJxMUMxRjBYQkMvclAvRVFkSUUyTXBST0J5OW1TZ2hsUlFibWxuZXc1N0tOU2F0alNnQjlRR3BSK1ZRegpkemlqWGQzNkI4ak1keG9Bd25jV3FnOGR3b3lUQUQ4bmE5M3huRXg1SWNuc2M1dlBNUUlEQVFBQm8xTXdVVEFkCkJnTlZIUTRFRmdRVXgzSm1ROHJ6cThwcGp3ckk3M3Ird2VseXV2VXdId1lEVlIwakJCZ3dGb0FVeDNKbVE4cnoKcThwcGp3ckk3M3Ird2VseXV2VXdEd1lEVlIwVEFRSC9CQVV3QXdFQi96QU5CZ2txaGtpRzl3MEJBUXNGQUFPQwpBUUVBVFJHTkNFOHN5Y29ya0t3TS9VMEQzUkQ4UTgrUVpQV0NWNEQ0NDZidVE3UWU2bFF5S2J3Rld5TGxianZUCjdtdFNWZHUyZVZSQ0x1SDFzYWVqWmF2aXhod3JYT0l2Q1JiS0tXT214VU51YVMveTFoaDFFMVYwRzVhSjlDQmoKQmhDU3dKT1hWQkhrL3BvKzJYdkxjSDVxeDBqK2JBTVNVeDR3Sk85aWhHT3RXMkhLMklLakdNT1VRZHNhd0pGbwp0YjFRMkNPajhCUVJzbVE4OGY5RFNTSDlTTkVFZHJLKzRxZGl6V3NFUFVPMFl1OEs5eFdlY3kzYjFEb216Nnk4CmxKaEhNYmJ0KzFjYXBXOXNuOW1RdGZzYUxwTXBsL21xc0VjdFJIdEZBMDhvK2hKWGFIaDZEVTBWN0lQNFlMVDQKUVNPclorelZQM1BRVFd6emp3V0NYeDg1dnc9PQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==" }]
  }
}

variables {
  owner       = "testowner"
  cost_center = "test"
}

run "the_namespace_is_restricted_and_gates_readiness_on_the_alb" {
  command = plan

  assert {
    condition = alltrue([
      kubernetes_namespace_v1.shiptrack.metadata[0].name == "shiptrack",
      kubernetes_namespace_v1.shiptrack.metadata[0].labels["pod-security.kubernetes.io/enforce"] == "restricted",
      kubernetes_namespace_v1.shiptrack.metadata[0].labels["pod-security.kubernetes.io/warn"] == "restricted",
      kubernetes_namespace_v1.shiptrack.metadata[0].labels["elbv2.k8s.aws/pod-readiness-gate-inject"] == "enabled",
    ])
    error_message = "shiptrack enforces the restricted Pod Security Standard and injects the ALB readiness gate."
  }
}

run "the_deployers_role_is_namespaced_and_bound_to_the_group" {
  command = plan

  assert {
    condition = alltrue([
      kubernetes_role_v1.deployer.metadata[0].namespace == "shiptrack",
      kubernetes_role_binding_v1.deployer.subject[0].kind == "Group",
      kubernetes_role_binding_v1.deployer.subject[0].name == "shiptrack-deployers",
      kubernetes_role_binding_v1.deployer.role_ref[0].name == "shiptrack-deployer",
    ])
    error_message = "The pipeline's group gets one Role, in the shiptrack namespace only."
  }

  assert {
    condition = alltrue([
      for r in kubernetes_role_v1.deployer.rule :
      !contains(r.resources, "roles") && !contains(r.resources, "rolebindings") && !contains(r.resources, "namespaces")
    ])
    error_message = "The deploy role cannot change RBAC or namespaces."
  }

  assert {
    condition = anytrue([
      for r in kubernetes_role_v1.deployer.rule :
      contains(r.api_groups, "elbv2.k8s.aws") && contains(r.resources, "targetgroupbindings")
      ]) && anytrue([
      for r in kubernetes_role_v1.deployer.rule :
      contains(r.api_groups, "keda.sh") && contains(r.resources, "scaledobjects") && contains(r.resources, "triggerauthentications")
    ])
    error_message = "The chart installs TargetGroupBindings, ScaledObjects, and TriggerAuthentications."
  }
}

run "the_controllers_use_the_service_accounts_that_have_roles" {
  command = plan

  assert {
    condition = alltrue([
      yamldecode(helm_release.lbc.values[0]).serviceAccount.name == "aws-load-balancer-controller",
      helm_release.lbc.namespace == "kube-system",
      yamldecode(helm_release.keda.values[0]).serviceAccount.operator.name == "keda-operator",
      helm_release.keda.namespace == "keda",
      yamldecode(helm_release.grafana.values[0]).serviceAccount.name == "grafana",
      helm_release.grafana.namespace == "monitoring",
    ])
    error_message = "Pod Identity associations are per namespace and service account; the charts must use the ones terraform/cluster bound."
  }
}

run "the_load_balancer_controller_is_configured_for_a_target_group_binding_setup" {
  command = plan

  assert {
    condition = alltrue([
      yamldecode(helm_release.lbc.values[0]).clusterName == "shiptrack",
      yamldecode(helm_release.lbc.values[0]).vpcId == "vpc-mock",
      yamldecode(helm_release.lbc.values[0]).enableServiceMutatorWebhook == false,
    ])
    error_message = "LBC knows the cluster and the VPC and leaves Services alone."
  }
}

run "the_charts_are_pinned" {
  command = plan

  assert {
    condition = alltrue([
      helm_release.lbc.version == "3.6.0",
      helm_release.keda.version == "2.21.0",
      helm_release.grafana.version == "10.5.15",
      helm_release.lbc.atomic,
      helm_release.keda.atomic,
      helm_release.grafana.atomic,
    ])
    error_message = "Every chart has an exact version and rolls back on failure."
  }
}

run "grafana_reads_amp_with_sigv4_and_has_no_ingress" {
  command = plan

  assert {
    condition = alltrue([
      yamldecode(helm_release.grafana.values[0]).service.type == "ClusterIP",
      yamldecode(helm_release.grafana.values[0]).datasources["datasources.yaml"].datasources[0].jsonData.sigV4Auth == true,
      yamldecode(helm_release.grafana.values[0]).datasources["datasources.yaml"].datasources[0].url == "https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-00000000-0000-0000-0000-000000000000/",
    ])
    error_message = "Grafana is ClusterIP and queries the workspace with SigV4."
  }

  assert {
    condition     = contains(keys(kubernetes_config_map_v1.dashboards.data), "app-red.json")
    error_message = "The dashboards in observability/grafana are provisioned."
  }
}

run "the_dashboards_are_valid_json" {
  command = plan

  assert {
    condition = alltrue([
      for name, body in kubernetes_config_map_v1.dashboards.data :
      can(jsondecode(body).uid) && can(jsondecode(body).panels)
    ])
    error_message = "Each dashboard parses and has a uid and panels."
  }
}
