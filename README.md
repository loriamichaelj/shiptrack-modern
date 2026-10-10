# shiptrack-modern

ShipTrack v2: the "after" stack of the EC2-to-EKS migration. The same API and UI as
[`shiptrack-legacy`](https://github.com/loriamichaelj/shiptrack-legacy), running on EKS, with each
of legacy's anti-patterns fixed. The fork is recorded, not hidden: the first commit imports legacy
`v1.0.0` unmodified (`docs/FORK.md`), and every later change to the application names the
remediation it implements (`REM-01` to `REM-16`, design §2) in its pull request and in the squash
commit that lands it.

- Design: [`docs/DESIGN.md`](docs/DESIGN.md)
- Decisions: [`docs/ADR.md`](docs/ADR.md)
- The fork record and how to check it: [`docs/FORK.md`](docs/FORK.md)
- The shared infrastructure it runs on, and the ALB weights that move traffic here: [`shiptrack-platform`](https://github.com/loriamichaelj/shiptrack-platform)

The API contract is frozen: it behaves exactly as legacy design §3.4 says, plus a short list of
additions (design §1). The UI source in `web/` is frozen until Wave 2 completes, so both stacks
serve the same build.

## What changed from legacy

| Area | Modern |
|---|---|
| Configuration and credentials | Environment settings; database credentials from Secrets Manager with a cache that refetches on an authentication failure (REM-01, REM-02) |
| Events | API puts them on SQS; `worker-events` applies them and publishes domain events to EventBridge; `worker-notify` consumes notifications (REM-06) |
| Proof of delivery | Objects in S3, downloaded through a short-lived presigned redirect (REM-05) |
| SLA scan | One statement flags breaches and records alerts, run as a CronJob (REM-09) |
| Health | `/healthz` never checks dependencies; `/readyz` checks the database and the schema revision (REM-07) |
| Observability | JSON logs with a request ID; Prometheus metrics on port 9090 only (REM-08, REM-15) |
| UI and headers | Served by the API from the image, with a strict CSP and security headers (REM-16) |
| Delivery | A multi-arch, non-root image by digest; a Helm chart; Terraform for the cluster; pipelines through OIDC |

## Layout

| Path | What it holds |
|---|---|
| `src/shiptrack/` | The application. `python -m shiptrack <api\|worker-events\|worker-notify\|sla-scan\|migrate>` selects the role |
| `migrations/` | Alembic, the same lineage as legacy |
| `web/` | The React UI, frozen |
| `tests/` | `unit/` and `integration/` (Postgres plus a moto server for SQS, S3, Secrets Manager, and EventBridge) |
| `Dockerfile` | Builds the UI, installs from `uv.lock`, and runs as uid 10001 |
| `compose.yaml` | Local only: the app, Postgres, and an AWS emulator |
| `charts/shiptrack/` | The Helm chart: [`charts/shiptrack/README.md`](charts/shiptrack/README.md) |
| `terraform/cluster/` | EKS, ECR, SQS, EventBridge, Pod Identity roles, Prometheus, and alarms; publishes `/shiptrack/modern/*` |
| `terraform/addons/` | The load balancer controller, KEDA, Grafana, the namespace, and the deploy role's RBAC. Applied after `cluster` |
| `terraform/modules/pod-role/` | One IAM role and Pod Identity association per service account |
| `scripts/` | `render-values.sh` (SSM to Helm values), `smoke.sh`, `local-init.sh` |
| `observability/grafana/` | Dashboards that `terraform/addons` provisions |

## Status

| Phase | State |
|---|---|
| M0 Fork | Done |
| M1 Application | Done: tests, lint, types, and the platform contract suite against the compose stack |
| M2 Image | Done: builds for amd64 and arm64, Trivy clean |
| M3 Terraform cluster, M4 addons | Written and tested offline; not applied |
| M5 Helm chart | Written; lint, kubeconform, and render tests pass; not installed on a cluster |
| M6 CI/CD | Written; not yet run on GitHub |
| M7 and later | Not started: SLO document and dashboards, runbooks and game days, Karpenter, wave 3 |

Nothing in this repository has been applied to AWS yet.

## Local development

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker (OrbStack works).

```sh
uv sync --frozen
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:5432:5432 postgres:17
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest
```

The tests create and drop their own databases, and start a moto server for the AWS APIs, so they need
no credentials. Set `SHIPTRACK_TEST_DATABASE_URL` to use another Postgres. The chart tests run
`helm template` and are skipped if `helm` is not installed.

To run the whole stack, with the UI at `http://localhost:8000/ui/` and metrics at `localhost:9090`:

```sh
export LOCALSTACK_AUTH_TOKEN=...      # LocalStack needs an account token
docker compose up --build -d
curl localhost:8000/readyz
docker compose down -v
```

The emulator answers to `localhost.localstack.cloud`, so a presigned proof-of-delivery URL opens from
your machine as well as from the containers.

### Checks the pipelines also run

```sh
terraform fmt -check -recursive terraform
for root in terraform/cluster terraform/addons; do
  terraform -chdir=$root init -backend=false && terraform -chdir=$root validate && terraform -chdir=$root test
done
tflint --recursive
checkov --config-file .checkov.yaml -d terraform
helm lint charts/shiptrack -f charts/shiptrack/ci-values.yaml
actionlint
```

## Pipelines

Nothing is applied from a workstation. Every AWS change is a workflow that assumes an OIDC role, and
the `dev` environment requires a reviewer.

| Workflow | Runs | Does |
|---|---|---|
| `ci.yml` | pull requests | Six parallel jobs: tests with a 75% coverage gate and a dependency audit; the UI checks; gitleaks; the image build with Trivy and an SBOM; Terraform checks; Helm lint, kubeconform, and Checkov |
| `terraform-pr.yml` | pull requests touching Terraform | A plan comment for both roots, addresses and actions only |
| `terraform-apply.yml` | push to `dev`, or by hand | Applies `cluster`, then `addons`, after one approval |
| `release.yml` | push to `dev` that changes the image | Builds each architecture natively, merges them, scans the pushed digest, and hands the digest on |
| `deploy.yml` | after a release, or by hand with a digest | `helm upgrade --atomic`, a smoke test through the ALB, and a rollback if it fails |

First deploy, in order: `terraform-apply`, then `release`, then `deploy` (it follows the release by
itself). Registering the modern target group with the ALB weights is a change in the platform
repository.

## Rules that apply here

- `dev` is the default and protected branch; work happens on short-lived branches and merges by pull
  request, squashed (ADR-0016). Name each remediation (`REM-nn`) in the pull request title or the
  squash commit body. A remediation that may need reverting on its own is its own pull request.
- No account IDs, ARNs with account IDs, ALB addresses, or secret values in committed files, logs, or
  PR comments. Use `<ACCOUNT_ID>` and friends. Plan files are never uploaded.
- Every IAM role and customer managed policy is named `<PREFIX>-...` (the `ROLE_PREFIX` repository
  variable) and carries the platform's `<PREFIX>-workload-boundary`.
