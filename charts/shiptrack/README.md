# shiptrack chart

The Helm chart for ShipTrack on EKS: the API, the events and notification workers, the SLA scan
CronJob, and the migration Job. The design is `docs/DESIGN.md` §7.

The chart installs into the `shiptrack` namespace, which `terraform/addons` creates, with the
Pod Security `restricted` profile and the ALB readiness-gate label. It needs the load balancer
controller and KEDA, also from `terraform/addons`.

## Values

| File | Holds |
|---|---|
| `values.yaml` | Safe defaults for everything |
| `values-dev.yaml` | Replicas, scaling, and pool sizes for dev. A unit test checks them against the database connection budget (ADR-0002) |
| `generated-values.yaml` | Not committed. `scripts/render-values.sh` writes it from the SSM contract: the queue URLs, bucket, secret ARNs, target group, security group, VPC CIDR, and image repository |
| `ci-values.yaml` | Placeholders for `helm lint`, `helm template`, and kubeconform |

`values.schema.json` makes rendering fail when a required value is missing or the image digest is
not `sha256:<64 hex>`. The image is always referenced by digest.

## Switches

| Value | Default | Meaning |
|---|---|---|
| `slaScan.suspend` | `true` | The SLA scan CronJob stays suspended until the legacy cron is removed (Wave 3) |
| `migrations.enabled` | `false` | Renders the pre-install and pre-upgrade migration Job. Turn on only after the schema ownership handoff (design §9.1) |
| `serviceAccount.automountToken` | `false` | Pod Identity injects its own token, so the default stays off; verified on the first deploy (ADR-0004) |
| `faultErrorRate`, `faultReadyFail` | `"0"`, `false` | Game days only |

## Render and check locally

```sh
helm lint . -f ci-values.yaml
helm template shiptrack . -f ci-values.yaml -f values-dev.yaml \
  | kubeconform -strict -kubernetes-version 1.34.0 -schema-location default \
      -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -
```

## Deploying

`deploy.yml` runs, with the approval of the `dev` environment:

```sh
scripts/render-values.sh generated-values.yaml
helm upgrade --install shiptrack charts/shiptrack -n shiptrack \
  -f charts/shiptrack/values-dev.yaml -f generated-values.yaml \
  --set image.digest=sha256:<digest> --atomic --wait --timeout 10m --history-max 10
```

Do not run it from a workstation. A migration hook is not undone by `--atomic` or `helm rollback`,
so schema changes must stay backward compatible.
