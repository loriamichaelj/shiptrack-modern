# shiptrack chart

The Helm chart for ShipTrack on EKS and, with `cloud: gcp`, on GKE: the API, the events and
notification workers, the SLA scan CronJob, and the migration Job. The design is `docs/DESIGN.md`.

The chart installs into the `shiptrack` namespace, which `terraform/addons` creates, with the
Pod Security `restricted` profile and the ALB readiness-gate label. It needs the load balancer
controller and KEDA, also from `terraform/addons`.

## Values

| File | Holds |
|---|---|
| `values.yaml` | Safe defaults for everything |
| `values-dev.yaml` | Replicas, scaling, and pool sizes for dev. A unit test checks them against the database connection budget |
| `generated-values.yaml` | Not committed. `scripts/render-values.sh` writes it from the SSM contract: the queue URLs, bucket, secret ARNs, target group, security group, VPC CIDR, and image repository |
| `ci-values.yaml` | Placeholders for `helm lint`, `helm template`, and kubeconform |
| `ci-values-gcp.yaml` | The same placeholders for `cloud: gcp`. The GCP repository holds the real GCP values and passes the identifying ones with `--set` |

`values.schema.json` makes rendering fail when a required value is missing or the image digest is
not `sha256:<64 hex>`. The image is always referenced by digest.

## Switches

| Value | Default | Meaning |
|---|---|---|
| `cloud` | `aws` | `aws` or `gcp`. Selects the block of settings (`aws` or `gcp`) the pods read and the objects rendered. The schema requires the selected cloud's block and nothing of the other's |
| `scaling.mode` | `keda` | `keda`: an HPA for the api and KEDA for the workers. `fixed`: the replica counts (`api.replicas`, `workerEvents.replicas`, `workerNotify.replicas`) with neither. GCP requires `fixed` |
| `spot` | `false` | GCP only. Puts every pod on GKE Spot capacity with the `cloud.google.com/gke-spot` node selector. The schema refuses it on AWS |
| `slaScan.suspend` | `true` | The SLA scan CronJob stays suspended until the legacy cron is removed (Wave 3) |
| `migrations.enabled` | `false` | Renders the pre-install and pre-upgrade migration Job. Turn on only after the schema ownership handoff |
| `serviceAccount.automountToken` | `false` | Pod Identity injects its own token, so the default stays off; verified on the first deploy |
| `faultErrorRate`, `faultReadyFail` | `"0"`, `false` | Game days only |

## What `cloud: gcp` changes

- The `TargetGroupBinding`, the KEDA objects, and the HPA are not rendered, and the pods read the `gcp` block (project, secret names, topics, subscriptions, bucket, and the signer) instead of the `aws` block.
- A `PodMonitoring` resource has the managed Prometheus scrape port 9090 every 60 seconds.
- The network policies admit the managed collectors (`gke-gmp-system` on Autopilot, `gmp-system` otherwise) to port 9090 and nothing to the api, which is reached with `kubectl port-forward`.
- Service accounts carry no annotation: the GKE workload identity binding names the Kubernetes service account.

The AWS render does not change; the chart tests and the CI render keep it that way.

## Render and check locally

```sh
helm lint . -f ci-values.yaml
helm template shiptrack . -f ci-values.yaml -f values-dev.yaml \
  | kubeconform -strict -kubernetes-version 1.34.0 -schema-location default \
      -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -
helm template shiptrack . -f ci-values-gcp.yaml | kubeconform -strict ...   # the same, for GCP
```

## Deploying

`deploy-app.yml` runs, with the approval of the `dev` environment:

```sh
scripts/render-values.sh generated-values.yaml
helm upgrade --install shiptrack charts/shiptrack -n shiptrack \
  -f charts/shiptrack/values-dev.yaml -f generated-values.yaml \
  --set image.digest=sha256:<digest> --atomic --wait --timeout 10m --history-max 10
```

Do not run it from a workstation. A migration hook is not undone by `--atomic` or `helm rollback`,
so schema changes must stay backward compatible.
