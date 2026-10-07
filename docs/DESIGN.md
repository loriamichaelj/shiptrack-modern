# ShipTrack Modern (v2.x) — Design Document

| | |
|---|---|
| **Repository** | `shiptrack-modern` |
| **Author** | M.L. |
| **Status** | v0.1 |
| **Last updated** | 2026-10-06 |
| **Related** | `shiptrack-platform/docs/DESIGN.md`, `shiptrack-legacy/docs/DESIGN.md` |
| **Specialization** | Migration, Optimization & Modernization (expected to be demonstrated at greater depth than the other topics) |

---

## 0. Instructions for the implementing agent

1. **Fork, don't rewrite.** The first commit imports `shiptrack-legacy` at tag `v1.0.0` **unmodified** (`src/`, `migrations/`, `alembic.ini`, `tests/`, `web/`, `pyproject.toml`, and `requirements*`). Record the source repo, tag, and commit SHA in `docs/FORK.md`. Every later refactor commit references the remediation it implements (for example `REM-06: replace in-process queue with SQS`).
2. **API contract is frozen.** The behavior in legacy design §3.4 must remain identical. The platform contract suite must pass against both stacks. The only allowed additions are `/healthz`, `/readyz`, the metrics server on port 9090, response headers `X-ShipTrack-Stack: modern`, `X-Request-Id`, and the REM-16 security headers, 503 `QUEUE_UNAVAILABLE` on the events endpoint, and the game-days-only `INJECTED_FAULT` 500 (§5.9). The contract suite recognizes both (legacy §3.4); `INJECTED_FAULT` is a failure outside game days. POD GET may return 302 → presigned URL. **The UI source in `web/` is frozen until Wave 2 completes**, because cutover gate G6 requires both stacks to serve an identical UI build.
3. **Schema changes are expand/contract only** and must follow the ownership handoff in §9.1. Helm migrations stay **disabled** until handoff.
4. **Never apply from a workstation.** Do not run `terraform apply`, `helm install/upgrade`, or `kubectl apply` against a real cluster. These run only inside GitHub Actions workflows with environment approval. OrbStack's local Kubernetes is fine for chart testing.
5. Pin all versions: Terraform modules, Helm charts, base-image digests, and GitHub Actions (by SHA).
6. Ask on ambiguity. Record decisions in `docs/ADR.md`. Items marked **[VERIFY]** must be checked against current documentation.
7. Follow the hard limits from the platform design: no secrets in git, state, or logs; every IAM role carries the platform permission boundary; no long-lived keys. The repository is public, so also follow platform §6.12: no account IDs, ARNs with account IDs, DNS names, or tokens in files, logs, comments, artifacts, or evidence.

---

## 1. Goals and measurable targets

| Goal | Legacy baseline (measured) | Target |
|---|---|---|
| Release speed | Deploy duration and 5xx during deploy, from legacy assessment | Commit → deployed < 15 min (excluding approval wait); **zero** ALB 5xx attributable to deploys |
| Reliability | No SLOs | SLOs in §11.1 met over the demo window; automated rollback on failed release |
| Security | AP-01…AP-04, AP-13, AP-14 findings | 0 fixable CRITICAL/HIGH in deployed images; no plaintext secrets; per-workload least privilege |
| Cost | `Stack=legacy` cost per 1M requests | Documented `Stack=modern` cost per 1M requests; ≥ 3 optimization actions with before/after evidence |
| Data integrity | Lost events (AP-06), duplicate SLA alerts (AP-09) | 0 lost events under deploy and node loss; exactly one SLA alert per breach |

---

## 2. Remediation map

| REM | Fixes | Remediation | Where |
|---|---|---|---|
| REM-01 | AP-01 | DB credentials fetched at runtime from Secrets Manager via EKS Pod Identity; never written to disk or Kubernetes Secrets | `src/shiptrack/config.py`, IAM |
| REM-02 | AP-02 | Runtime uses `shiptrack_app` (DML only); migrations Job uses `shiptrack_migrator` | Helm, IAM |
| REM-03 | AP-03 | One ServiceAccount + IAM role per workload, resource-scoped policies, platform boundary | §8.1, §7 |
| REM-04 | AP-04 | Nodes: IMDSv2 required, hop limit 1 (pods cannot reach the node role) | Launch template / EC2NodeClass |
| REM-05 | AP-05 | POD stored in S3; no stickiness; presigned GET | App, platform bucket |
| REM-06 | AP-06 | API → SQS (202 only after `SendMessage` succeeds) → worker; DLQ; idempotent apply | App, §8.1 |
| REM-07 | AP-07 | `/healthz` liveness, `/readyz` readiness, startup probe; LBC pod readiness gates | App, Helm |
| REM-08 | AP-08 | Structured JSON logs to stdout with `request_id`; shipped by the CloudWatch Observability add-on (Fluent Bit) | App, add-on |
| REM-09 | AP-09 | Single CronJob (`concurrencyPolicy: Forbid`) + atomic `UPDATE … RETURNING`; unique constraint added in Wave 3 | App, Helm, migration |
| REM-10 | AP-10 | HPA (API), KEDA (workers), Karpenter consolidation, Graviton | Helm, add-ons |
| REM-11 | AP-11 | No app data on node disks; gp3 node root volumes sized to need | Terraform |
| REM-12 | AP-12 | Immutable images by digest; rolling update `maxUnavailable: 0`; readiness gates + preStop + 30 s deregistration | Helm, platform TG |
| REM-13 | AP-13 | Trivy, Checkov, gitleaks, kubeconform gates in CI; Inspector ECR continuous scanning | CI |
| REM-14 | AP-14 | Images rebuilt on base updates; nodes on the latest EKS AL2023 AMI with Karpenter drift replacement | CI, Karpenter |
| REM-15 | AP-15 | RED metrics, business metrics, SLO burn-rate alerts | App, §11 |
| REM-16 | AP-16 | Security headers on every response: strict CSP, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'` | App middleware, §5.11 |

---

## 3. Architecture

```
                         ALB (platform) ── weighted / header / path rules
                                  │
                         tg-modern (ip :8000)  ◄── TargetGroupBinding (LBC)
                                  │
 ┌────────────────────────── EKS cluster "shiptrack" ───────────────────────────┐
 │ namespace shiptrack (PSA restricted, readiness-gate injection)               │
 │                                                                              │
 │  api (Deployment, HPA 2–10) ──SendMessage──► SQS carrier-events ──► DLQ      │
 │     │  │                                          │                          │
 │     │  └─ PutObject/presign ─► S3 POD (platform)  ▼                          │
 │     │                                 worker-events (KEDA 1–10)              │
 │     │                                    │   │                               │
 │     ▼                                    │   └─PutEvents─► EventBridge bus   │
 │  RDS (platform) ◄────────────────────────┘                  "shiptrack"      │
 │     ▲                                              rule ─► SQS notifications │
 │     │                                                         │  └─► DLQ     │
 │  sla-scan (CronJob, */5)                       worker-notify (KEDA 0–3)      │
 │  migrate (Helm hook Job, disabled until handoff)                             │
 │                                                                              │
 │ add-ons: VPC CNI (netpol, prefix delegation) · CoreDNS · kube-proxy ·        │
 │   Pod Identity agent · CloudWatch Observability (Container Insights +        │
 │   Fluent Bit) · metrics-server · AWS LB Controller · KEDA · Karpenter ·      │
 │   Grafana                                                                    │
 └──────────────────────────────────────────────────────────────────────────────┘
   AMP workspace + managed scraper ◄── pod :9090/metrics      ECR shiptrack/app
```

---

## 4. Repository layout

```
shiptrack-modern/
├── src/shiptrack/              # Forked from legacy v1.0.0, then refactored
├── web/                        # React UI, forked unchanged (frozen until Wave 2)
├── migrations/                 # Alembic (same lineage as legacy)
├── tests/{unit,integration}/
├── pyproject.toml  uv.lock
├── Dockerfile  .dockerignore
├── compose.yaml                # Local only: app + Postgres + LocalStack
├── charts/shiptrack/
│   ├── Chart.yaml  values.yaml  values-dev.yaml  values.schema.json  ci-values.yaml
│   └── templates/
│       ├── _helpers.tpl
│       ├── serviceaccounts.yaml
│       ├── deployment-api.yaml  service-api.yaml  hpa-api.yaml  pdb-api.yaml
│       ├── targetgroupbinding.yaml
│       ├── deployment-worker-events.yaml  scaledobject-worker-events.yaml
│       ├── deployment-worker-notify.yaml  scaledobject-worker-notify.yaml
│       ├── triggerauthentication.yaml
│       ├── cronjob-sla-scan.yaml
│       ├── job-migrate.yaml
│       └── networkpolicies.yaml
├── terraform/
│   ├── cluster/                # EKS, nodes, ECR, SQS, EventBridge, IAM, Pod Identity, AMP, alarms, SSM outputs
│   └── addons/                 # Helm releases + cluster-scoped manifests (needs a live cluster)
├── scripts/
│   ├── render-values.sh        # SSM → generated Helm values
│   └── smoke.sh
├── observability/
│   ├── grafana/*.json
│   └── cloudwatch/*.json
├── gamedays/GD-1..GD-4/        # README (hypothesis, steps, signals) + evidence/
├── docs/
│   ├── DESIGN.md  ADR.md  FORK.md  slo.md
│   ├── runbooks/
│   │   ├── deploy-rollback.md
│   │   ├── dlq-redrive.md
│   │   ├── canary-regression.md
│   │   ├── node-failure.md
│   │   └── wave-3-contract-migration.md
│   ├── migration/              # wave-N/ evidence (§9.3) and dora.csv
│   ├── security/scan-report.md
│   └── cost/analysis.md
├── .github/
│   ├── workflows/
│   │   ├── ci.yml  release.yml  deploy.yml
│   │   └── terraform-pr.yml  terraform-apply.yml
│   └── dependabot.yml          # github-actions, uv, npm, docker
├── .trivyignore  .tflint.hcl  .checkov.yaml  .gitleaks.toml  .gitignore
└── README.md
```

**Why two Terraform roots:** the `kubernetes`, `helm`, and `kubectl` providers cannot be reliably configured from a cluster created in the same apply. `cluster/` must be applied before `addons/`. The state keys are `modern/cluster/dev.tfstate` and `modern/addons/dev.tfstate`.

---

## 5. Application refactor specification

### 5.1 Tooling changes
- Keep the forked `pyproject.toml` (tool config), declare dependencies in it, and replace `requirements*` with `uv.lock` (hash-locked).
- Python stays 3.12.
- Replace gunicorn with `uvicorn` (single process; one worker per pod — scaling is horizontal).
- Add `structlog`, `prometheus-client`, and `aws-secretsmanager-caching` (or an equivalent small cache).

### 5.2 Configuration (REM-01)
Configuration comes from `pydantic-settings` environment variables. INI support is removed.

| Variable | Used by | Notes |
|---|---|---|
| `SHIPTRACK_DB_SECRET_ARN` | all except migrate | `shiptrack/dev/db/app` |
| `SHIPTRACK_DB_MIGRATOR_SECRET_ARN` | migrate | |
| `SHIPTRACK_EVENTS_QUEUE_URL` | api, worker-events | |
| `SHIPTRACK_NOTIFY_QUEUE_URL` | worker-notify | |
| `SHIPTRACK_EVENT_BUS_NAME` | worker-events | |
| `SHIPTRACK_POD_BUCKET` | api | |
| `SHIPTRACK_SCHEMA_COMPAT` | all | Comma-separated Alembic revisions this build tolerates (§9.1) |
| `SHIPTRACK_LOG_LEVEL` | all | default `INFO` |
| `SHIPTRACK_DB_POOL_SIZE` / `_MAX_OVERFLOW` | all | set per workload in Helm (§5.10) |
| `SHIPTRACK_FAULT_ERROR_RATE` | api | default `0`; game days only |
| `SHIPTRACK_FAULT_READY_FAIL` | api | default `false`; game days only |
| `AWS_REGION` | all | |

**Secret handling:**
- Fetch the secret at startup and cache it in memory.
- On a psycopg authentication failure, invalidate the cache, refetch once, and retry (this makes the app rotation-ready).
- Never log secret values. Add a logging filter that redacts keys named `password`.

### 5.3 Single image, multiple entrypoints
`python -m shiptrack <command>`:

| Command | Process |
|---|---|
| `api` | `uvicorn shiptrack.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'` (safe because NetworkPolicy admits only VPC-CIDR traffic on 8000) + metrics server :9090 |
| `worker-events` | SQS consumer loop + metrics/health :9090 |
| `worker-notify` | SQS consumer loop + metrics/health :9090 |
| `sla-scan` | One-shot; exits 0/1 |
| `migrate` | `alembic upgrade head` with migrator credentials; refuses to run unless `SHIPTRACK_MIGRATIONS_ENABLED=true` |

### 5.4 Event ingestion (REM-06)
**API path:** validate the body → confirm the shipment exists (DB read; preserves the 404 contract) → `SendMessage` to `carrier-events` → return 202.
- Message body: `{"shipment_id", "idempotency_key", "event_type", "location", "occurred_at", "payload", "received_at", "request_id"}`. Message attribute `idempotency_key`.
- If `SendMessage` fails, return **503** `{"error":{"code":"QUEUE_UNAVAILABLE"}}`. Never return 202 for an event that was not durably queued.

**worker-events:**
- Long poll 20 s, batch up to 10, visibility timeout 60 s.
- Each message is processed in its own DB transaction using the legacy §3.3 rules (`INSERT … ON CONFLICT (idempotency_key) DO NOTHING`, out-of-order and invalid handling).
- After commit, if the status transitioned to `DELIVERED` or `EXCEPTION`, call `PutEvents` on bus `shiptrack`:
  - `Source=shiptrack.events`
  - `DetailType=ShipmentDelivered|ShipmentException`
  - Detail: `{event_id: <idempotency_key>, shipment_id, tracking_number, status, occurred_at}`
  - Retry 3× with backoff.
- Delete only successfully processed messages (individual deletes). Failures are left for redelivery and reach the DLQ after `maxReceiveCount` 5.
- **SIGTERM:** stop polling, finish in-flight messages, exit. `terminationGracePeriodSeconds` 90.
- **Known trade-off:** the DB commit and `PutEvents` are a dual write; a crash between them loses a notification (not data). A transactional outbox is a stretch goal and should be written up in `docs/ADR.md`.

**worker-notify:** consumes `notifications` (EventBridge → SQS envelope), logs a structured `notification_sent` record, and increments a metric. It is idempotent on `detail.event_id` via an in-memory LRU cache (the duplicate window is acceptable for a demo; documented).

### 5.5 SLA scan (REM-09)
Run in one transaction:

```sql
WITH breached AS (
  UPDATE shiptrack.shipments
     SET sla_breached = true, sla_breached_at = now(), updated_at = now()
   WHERE status <> 'DELIVERED' AND promised_delivery_at < now() AND NOT sla_breached
  RETURNING id
)
INSERT INTO shiptrack.sla_alerts (shipment_id, detected_by)
SELECT id, :pod_name FROM breached;
```

This is correct regardless of how many scanners run. The CronJob stays `suspend: true` until Wave 3, when the legacy cron is removed first. Log `sla_scan_completed` with `breaches` and `duration_ms`. This record also serves as the heartbeat signal for alarms.

### 5.6 POD storage (REM-05)
- **Upload:** stream to `s3://<bucket>/pod/{shipment_id}/{document_id}` with `upload_fileobj`, computing the sha256 while streaming. The bucket default applies SSE-KMS. Store `storage_uri = s3://…`. Response shape is unchanged.
- **Download:**
  - `s3://` → **302** to a presigned GET URL (TTL 300 s).
  - `file://` (an unmigrated legacy record) → 404 + `pod_not_migrated` log + metric. Cutover gate G-POD (§9.2) limits this to the sync window described in legacy §8 (about 1–2 minutes after a POD is uploaded to legacy).
- Starlette spools uploads over 1 MiB to `/tmp`, so mount an `emptyDir` at `/tmp` (`sizeLimit: 64Mi`) because the root filesystem is read-only.

### 5.7 Health endpoints (REM-07)

| Endpoint | Port | Logic |
|---|---|---|
| `GET /` | 8000 | `OK` (legacy compatibility) |
| `GET /healthz` | 8000 | 200 if the process/event loop is responsive. **Never** checks dependencies. |
| `GET /readyz` | 8000 | 503 if draining (SIGTERM received) or `FAULT_READY_FAIL`; else `SELECT 1` with a 1 s timeout (result cached 2 s); 200/503 |
| `GET /healthz` | 9090 (workers) | 503 if the poll loop has not heartbeated for > 120 s |

**Gotcha (document in the README):** if RDS is down, every pod fails readiness → every target in tg-modern is unhealthy → the **ALB fails open** and routes to all targets anyway. This is accepted. Readiness on the DB still protects against single-pod bad state.

### 5.8 Observability in the app (REM-08, REM-15)

**Logs:** structlog JSON on stdout with fields `ts`, `level`, `event`, `logger`, `request_id` (from `X-Request-Id`, else `X-Amzn-Trace-Id`, else a generated UUID; echoed back in the response header), `route` (templated), `method`, `status`, `duration_ms`, and `shipment_id` where relevant. Health-check access logs are dropped (cost). The same middleware sets `X-ShipTrack-Stack: modern` on every response.

**Metrics:** served on **port 9090 only**. ALB forwards everything on 8000, so serving `/metrics` on 8000 would expose it to the internet.

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | counter | `route` (templated, never the raw path), `method`, `status_class` |
| `http_request_duration_seconds` | histogram | `route`, `method`; buckets .005…5 |
| `shiptrack_events_enqueued_total` | counter | `result` (ok/failed) |
| `shiptrack_events_processed_total` | counter | `result` (applied/duplicate/out_of_order/invalid/error) |
| `shiptrack_event_apply_lag_seconds` | histogram | — (`now - received_at` at apply) |
| `shiptrack_notifications_sent_total` | counter | `detail_type` |
| `shiptrack_sla_breaches_total` | counter | — |
| `shiptrack_pod_uploads_total` | counter | `result` |
| `shiptrack_db_pool_checked_out` | gauge | — |

**Cardinality gotcha:** the route label must be the FastAPI route template (`/api/v1/shipments/{id}`). Labeling by raw path creates a metric series per shipment.

### 5.9 Fault injection (game days only)
- Middleware returns 500 (error envelope code `INJECTED_FAULT`) for `SHIPTRACK_FAULT_ERROR_RATE` of non-health requests.
- `SHIPTRACK_FAULT_READY_FAIL=true` makes `/readyz` return 503.
- Both log a WARNING at startup.
- `values-dev.yaml` defaults both to off. Game days set them via `--set` on a dedicated release, never by committing them.

### 5.10 Database connection budget
- SQLAlchemy settings: `pool_pre_ping=True`, `pool_recycle=300`, with pool sizes set per workload through Helm env:

| Workload | `pool_size` / `max_overflow` | Why |
|---|---|---|
| api | 4 / 2 | One uvicorn process; sync endpoints run in a threadpool |
| worker-events | 2 / 0 | Messages are processed sequentially |
| sla-scan, migrate | 1 / 1 | One-shot |
| worker-notify | — | No DB access |

- Document the arithmetic in `docs/ADR.md`. Worst case during coexistence:

| Consumer | Max replicas | Conns each | Total |
|---|---|---|---|
| legacy (2 hosts × 4 workers × 15 SQLAlchemy default) | — | — | 120 |
| legacy SLA cron (2 hosts) | — | 2 | 4 |
| api | 10 | 6 | 60 |
| worker-events | 10 | 2 | 20 |
| sla-scan + migrate | 1 each | 2 | 4 |
| legacy PodSync (2 hosts) + evidence scripts | — | 2 each | 6 |
| **Total** | | | **214** |

  This must stay ≤ 60% of `db_max_connections` (≈ 240 of ≈ 400 on `db.t4g.medium`). Raising HPA/KEDA maxima or pool sizes means re-running this arithmetic; if the result exceeds the budget, record RDS Proxy as the decision in `docs/ADR.md`.
- Add a unit test asserting that the pool settings × the HPA/KEDA max replica counts in `values-dev.yaml` stay within the configured budget.

---

### 5.11 UI serving and security headers (REM-16)

**Serving:** the React build is baked into the image at `/app/web/dist`. FastAPI serves:
- `/ui/assets/*` via `StaticFiles`, with `Cache-Control: public, max-age=31536000, immutable`
- `/ui` and `/ui/{path:path}` → `index.html`, with `Cache-Control: no-cache` (SPA fallback)

URLs, cache headers, and HTML are identical to legacy (contract). The UI is not served on port 9090. For metrics, the `route` label on UI requests is the template `/ui/{path}`, never the raw path.

**Security headers** (middleware, every port-8000 response):
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000` only when the platform `base_url` is HTTPS

**Tests:** assert the headers in a unit test, and add a build check that the generated `index.html` contains no inline `<script>` or `<style>` (either would be blocked by this CSP).

**Not in scope (roadmap):** serving the UI from S3 + CloudFront. It decouples UI deploys from API deploys, adds edge caching, and removes the need for the sticky UI listener rule (platform R-08). It makes a good "next steps" slide.

## 6. Container image

```dockerfile
# syntax=docker/dockerfile:1
# Base images pinned by digest; Renovate/Dependabot updates them (REM-14)
FROM --platform=$BUILDPLATFORM node:24-slim@sha256:<digest> AS web
# Node version must equal web/.nvmrc and legacy's UI build (cutover gate G6)
# npm ci && npm run build in web/ → /web/dist

FROM python:3.12-slim@sha256:<digest> AS build
# uv from its official image, pinned by digest
# install deps from uv.lock into /app/.venv (--frozen --no-dev), then the project

FROM python:3.12-slim@sha256:<digest>
# - non-root user uid/gid 10001, no home write requirements
# - COPY --from=build /app/.venv /app/.venv ; COPY src ; COPY --from=web /web/dist /app/web/dist
# - ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH
# - OCI labels: org.opencontainers.image.{source,revision,created,title}
# - USER 10001 ; EXPOSE 8000 9090
ENTRYPOINT ["python", "-m", "shiptrack"]
CMD ["api"]
```

- No `HEALTHCHECK` instruction (Kubernetes probes handle health).
- Target image size < 200 MB.
- `.dockerignore` excludes tests, `.git`, terraform, charts, and `web/node_modules`.
- **Multi-arch:** `linux/amd64,linux/arm64`. Build each architecture natively in a matrix (`ubuntu-24.04` and `ubuntu-24.04-arm`; arm64 runners are free and generally available for public repositories), push the per-arch digests, then merge them with `docker buildx imagetools create`. No QEMU. Before the merge, assert that `/app/web/dist/assets` has identical file names in both architecture images (§10.2), so the UI hashes cannot differ by architecture.
- **Tagging:** `sha-<full git sha>`. ECR tags are **IMMUTABLE**. Deployments reference the **digest**, never a tag.

---

## 7. Kubernetes and Helm

### 7.1 Namespace
`shiptrack`, created by `terraform/addons` (not by Helm), with labels:
- `pod-security.kubernetes.io/enforce: restricted`
- `pod-security.kubernetes.io/warn: restricted`
- `elbv2.k8s.aws/pod-readiness-gate-inject: enabled`

### 7.2 Workloads

| Workload | Kind | Scaling | Resources (req / mem limit) | Grace |
|---|---|---|---|---|
| api | Deployment | HPA CPU 60%, min 2 max 10; scale-down stabilization 300 s | 250m, 256Mi / 512Mi | 45 s |
| worker-events | Deployment | KEDA `aws-sqs-queue`, `queueLength` 20, min 1 max 10 | 100m, 256Mi / 512Mi | 90 s |
| worker-notify | Deployment | KEDA, `queueLength` 20, **min 0** max 3 | 50m, 128Mi / 256Mi | 60 s |
| sla-scan | CronJob `*/5 * * * *` | `concurrencyPolicy: Forbid`, `startingDeadlineSeconds: 120`, `activeDeadlineSeconds: 240`, `backoffLimit: 1`, `suspend: {{ .Values.slaScan.suspend }}` (default **true**) | 100m, 128Mi / 256Mi | — |
| migrate | Job (Helm hook `pre-install,pre-upgrade`, weight -5, delete policy `before-hook-creation,hook-succeeded`) | rendered only if `migrations.enabled` (default **false**) | 100m, 128Mi / 256Mi | — |

**No CPU limits** (avoids CFS throttling; requests drive scheduling and HPA). Memory limits are set.

**Common pod spec:**
- `securityContext`: `runAsNonRoot: true`, `runAsUser: 10001`, `seccompProfile: RuntimeDefault`
- Container: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`
- `emptyDir` `/tmp`
- `topologySpreadConstraints`: zone (`maxSkew 1`, `ScheduleAnyway`) and hostname (`maxSkew 1`, `ScheduleAnyway`)
- `automountServiceAccountToken: false` **[VERIFY Pod Identity credential injection still works with it disabled; if not, enable it and record it in `docs/ADR.md`]**

**api probes:**
- startup `/healthz`: period 2, failure 30
- liveness `/healthz`: period 10, timeout 2, failure 3
- readiness `/readyz`: period 5, timeout 2, failure 2

**Zero-downtime termination (REM-12):** rolling update `maxSurge: 25%`, `maxUnavailable: 0`, plus:
- LBC readiness gate: a pod is not Ready until its ALB target is healthy.
- `preStop` native sleep action, 15 s (`lifecycle.preStop.sleep.seconds`; GA since Kubernetes 1.34, so the image needs no shell or `sleep` binary).
- Platform TG deregistration delay 30 s.
- uvicorn graceful shutdown on SIGTERM.

**PDB:** api `minAvailable: 1`; worker-events `maxUnavailable: 1`.

### 7.3 Identity

| ServiceAccount | IAM role (Pod Identity) | Policy (resource-scoped) |
|---|---|---|
| `shiptrack-api` | `shiptrack-modern-api` | `sqs:SendMessage` on events queue; `s3:PutObject`/`GetObject` on `pod/*`; `secretsmanager:GetSecretValue` on the app secret; `kms:Decrypt`/`GenerateDataKey` via `s3`/`secretsmanager` |
| `shiptrack-worker-events` | `shiptrack-modern-worker-events` | `sqs:ReceiveMessage`/`DeleteMessage`/`ChangeMessageVisibility`/`GetQueueAttributes` on events queue; `events:PutEvents` on the bus; app secret + KMS via secretsmanager |
| `shiptrack-worker-notify` | `shiptrack-modern-worker-notify` | SQS consume on notifications queue |
| `shiptrack-sla-scan` | `shiptrack-modern-sla-scan` | app secret + KMS |
| `shiptrack-migrate` | `shiptrack-modern-migrate` | migrator secret + KMS |

All roles: prefix `shiptrack-modern-`, `permissions_boundary` = the platform boundary, and trust principal `pods.eks.amazonaws.com` with `sts:AssumeRole` + `sts:TagSession`.

### 7.4 Ingress and network

**TargetGroupBinding** `shiptrack-api`:
- `serviceRef: {name: shiptrack-api, port: 8000}`
- `targetGroupARN: {{ .Values.alb.targetGroupArn }}`
- `targetType: ip`
- `networking.ingress`: from `{{ .Values.alb.securityGroupId }}` to port 8000/TCP (LBC manages the node SG rule)

**Service** `shiptrack-api`: ClusterIP, port 8000 only.

**NetworkPolicies** (VPC CNI network policy enabled):
- Default deny ingress in the namespace.
- Allow api:8000 from the VPC CIDR (ALB ENIs).
- Allow :9090 on all pods from the VPC CIDR (AMP managed scraper ENIs).
- Egress is unrestricted (documented; the VPC CNI has no FQDN egress policy — stretch goal).

### 7.5 Values

**`values.yaml`** holds safe defaults.

**`values-dev.yaml`** holds replica, scaling, and resource settings.

**`scripts/render-values.sh`** reads `/shiptrack/platform/*` and `/shiptrack/modern/*` from SSM and writes `generated-values.yaml`:
- `alb.targetGroupArn`, `alb.securityGroupId`
- Queue URLs, bus name, bucket, secret ARNs, region, VPC CIDR

**CI-provided values:** `--set image.repository=… --set image.digest=sha256:…`

**`values.schema.json`** requires `image.digest` (pattern `^sha256:[a-f0-9]{64}$`), `alb.targetGroupArn`, and the queue URLs, and fails rendering if any are missing.

---

## 8. Infrastructure (Terraform)

### 8.1 `terraform/cluster`

**Inputs:** platform SSM contract (data sources) and variables (`kubernetes_version`, `admin_role_arns`, `github_org`).

**EKS**
- Module `terraform-aws-modules/eks/aws` `~> 21.0` (requires AWS provider ≥ 6.0). v21 notes for the implementer: input variables dropped the `cluster_` prefix (for example `name`, `kubernetes_version`); built-in IRSA was removed in favor of Pod Identity; node IMDS hop limit defaults to 1; EKS `deletion_protection` is supported and must be set `true`. Use the same major for the `//modules/karpenter` submodule.
- Name `shiptrack`
- `kubernetes_version = "1.36"` (pinned; the newest version in EKS standard support as of October 2026, with standard support through roughly August 2027 **[VERIFY end date]**). Falling into extended support raises the control-plane price about 6× (≈ $0.60 vs $0.10 per cluster-hour) — a cost gotcha.
- `authentication_mode = "API"` (access entries; the `aws-auth` ConfigMap is not used)
- **Access entries:**

| Principal | Access |
|---|---|
| `admin_role_arns` (humans) | `AmazonEKSClusterAdminPolicy` (cluster) |
| `shiptrack-modern-apply` | Cluster admin (needed by `addons/`) |
| `shiptrack-modern-plan` | `AmazonEKSViewPolicy` (cluster) |
| `shiptrack-modern-deploy` | `kubernetes_groups = ["shiptrack-deployers"]`, bound to a namespace Role in `addons/` |

- Endpoint public + private, `public_access_cidrs = var.eks_public_cidrs` (default `["0.0.0.0/0"]` because GitHub-hosted runners have no stable IPs). **Risk M-R1.** The enterprise answer is a private-only endpoint + self-hosted runners in the VPC.
- Secrets envelope encryption with its own CMK `alias/shiptrack-eks`.
- Control-plane logs `api`, `audit`, `authenticator` with 14-day retention. Audit-log volume is a cost line — measure it.

**EKS managed add-ons** (versions pinned):
- `vpc-cni`: `ENABLE_PREFIX_DELEGATION=true`, `enableNetworkPolicy=true`
- `coredns`
- `kube-proxy`
- `eks-pod-identity-agent`
- `amazon-cloudwatch-observability`: Container Insights enhanced observability + Fluent Bit; Pod Identity role
- `metrics-server` (EKS **community** add-on: AWS validates version compatibility and supports lifecycle API operations only, not the software itself)

**Managed node group `system`**
- AL2023 EKS-optimized arm64 AMI
- `m7g.large` (min 2, max 3, desired 2)
- Launch template: IMDSv2 required, hop limit 1, gp3 40 GiB encrypted
- Attach `sg_db_client_id` to the node security group. This grants **node-level** DB access, so every pod on the node can reach RDS. Security Groups for Pods would be stricter; that is a stretch item.
- Phases M3–M8: all workloads run here. Phase M9: taint `CriticalAddonsOnly=true:NoSchedule` and move app workloads to Karpenter.

**Karpenter (Phase M9)**
- Submodule `eks//modules/karpenter`: controller IAM via Pod Identity, node role + access entry, interruption SQS queue + EventBridge rules (spot interruption, rebalance, instance state change).

**ECR**
- `shiptrack/app`, `image_tag_mutability = "IMMUTABLE"`, KMS (`alias/shiptrack-eks` or its own key)
- Lifecycle: keep the latest 30 images tagged `sha-*`; expire untagged images after 1 day
- Repository policy: same-account pull only
- Inspector enhanced scanning is enabled at account level by platform

**SQS** (encrypted with SSE-SQS — no KMS request cost; optimization O-M8; switch to a CMK if compliance requires and record it in `docs/ADR.md`)

| Queue | Visibility | Retention | Long poll | Redrive |
|---|---|---|---|---|
| `shiptrack-carrier-events` | 60 s | 4 d | 20 s | → `-dlq`, maxReceiveCount 5 |
| `shiptrack-carrier-events-dlq` | — | 14 d | — | redrive-allow from source |
| `shiptrack-notifications` | 60 s | 4 d | 20 s | → `-dlq`, maxReceiveCount 5 |
| `shiptrack-notifications-dlq` | — | 14 d | — | |

The notifications queue policy allows `events.amazonaws.com` with `aws:SourceArn` set to the rule ARN.

**EventBridge**
- Custom bus `shiptrack`
- Rule `shiptrack-notify`: `source = shiptrack.events`, detail-type in [`ShipmentDelivered`, `ShipmentException`] → notifications queue
- **Archive** with 7-day retention, for replay during incident recovery

**IAM roles:** as listed in §7.3, plus:
- `shiptrack-modern-lbc` (official LBC policy JSON vendored at the chart's version)
- `shiptrack-modern-keda` (`sqs:GetQueueAttributes` on both queues)
- `shiptrack-modern-cwagent` (`CloudWatchAgentServerPolicy`)
- `shiptrack-modern-grafana` (`aps:QueryMetrics`, `aps:GetLabels`, `aps:GetSeries`, `aps:GetMetricMetadata`)
- Karpenter roles

All use Pod Identity associations in namespace `shiptrack` or the add-on's namespace, and all carry the boundary.

**Amazon Managed Service for Prometheus**
- Workspace `shiptrack`
- Managed scraper (agentless) on the cluster. The scrape config uses Kubernetes SD for pods annotated `prometheus.io/scrape: "true"`, port 9090.

**Alarms (modern-owned)** → platform SNS topics:

| Alarm | Condition | Sev |
|---|---|---|
| events-queue-age | `ApproximateAgeOfOldestMessage > 120 s` 5 min | SEV2 |
| events-queue-age-critical | `> 600 s` 5 min | SEV1 |
| events-dlq-visible | `ApproximateNumberOfMessagesVisible > 0` | SEV2 |
| notify-dlq-visible | same | SEV2 |
| pod-restarts | Container Insights `pod_number_of_container_restarts` > 3 in 10 min (namespace `shiptrack`) | SEV2 |
| sla-scan-heartbeat | Log metric filter `{ $.event = "sla_scan_completed" }`, sum < 1 over 15 min, `treat_missing_data = breaching` — **created disabled** (`actions_enabled = false`) until Wave 3 | SEV2 |
| slo-availability-fast-burn | §11.1 | SEV1 |
| slo-availability-slow-burn | §11.1 | SEV2 |

**Outputs → SSM** `/shiptrack/modern/`: `cluster_name`, `ecr_repository_url`, `events_queue_url`, `events_dlq_url`, `notify_queue_url`, `notify_dlq_url`, `event_bus_name`, `amp_workspace_id`.

### 8.2 `terraform/addons`

Providers: `helm`, `kubernetes`, and `kubectl` (alekc/kubectl). `kubernetes_manifest` requires CRDs at plan time, which breaks first-time applies — this is why `kubectl` is used for CRs.

| Release / manifest | Notes |
|---|---|
| `aws-load-balancer-controller` (chart pinned) | `clusterName`, `vpcId`, `enableServiceMutatorWebhook=false`, Pod Identity SA |
| `keda` (chart pinned) | Operator SA has a Pod Identity association to `shiptrack-modern-keda`. `TriggerAuthentication` uses `podIdentity.provider: aws` (operator credentials from the default SDK chain). Do not use `aws-eks` (deprecated, IRSA-specific). Leave `identityOwner` at its default (`keda`) so the operator's own Pod Identity credentials are used |
| `karpenter` (Phase M9) | + `EC2NodeClass` (AL2023, discovery tag subnets/SG, IMDSv2 hop 1, gp3) and NodePools via `kubectl_manifest` |
| `grafana` (chart pinned) | ClusterIP only (access via `kubectl port-forward`); AMP datasource with SigV4 via Pod Identity; dashboards from `observability/grafana` via ConfigMap provisioning |
| Namespace `shiptrack` | Labels per §7.1 |
| Role `shiptrack-deployer` + RoleBinding to group `shiptrack-deployers` | Namespace-scoped: core workload kinds, HPA, PDB, NetworkPolicy, ServiceAccount, Job/CronJob, `targetgroupbindings.elbv2.k8s.aws`, `scaledobjects/triggerauthentications.keda.sh`, Secrets (Helm release storage) |

**Karpenter NodePools (M9):**

| NodePool | Capacity | Arch | Disruption |
|---|---|---|---|
| `api` | on-demand | arm64 (amd64 allowed) | `WhenEmptyOrUnderutilized`, `consolidateAfter: 5m`, budget 1 node |
| `workers` | **spot** + on-demand fallback | arm64, amd64 | `WhenEmptyOrUnderutilized`, `consolidateAfter: 1m` |

Both: instance categories c/m/r, generation > 5, `limits.cpu: 32`. Workloads select a pool via `nodeSelector`/affinity in `values-dev.yaml`.

---

## 9. Coexistence and cutover (specialization core)

### 9.1 Schema ownership handoff

| Period | Schema owner | Legacy `RUN_MIGRATIONS` | Modern `migrations.enabled` | Rule |
|---|---|---|---|---|
| Before and during Waves 0–2 | **legacy** | true | false | Modern must run against legacy's head revision |
| After Wave 2 reaches 100% + soak | **modern** | false | true | All migrations expand/contract; legacy (scaled down but possibly rolled back to) must tolerate them until decommission |

**Compatibility guard:** at startup, the app reads `alembic_version`. If the revision is not in `SHIPTRACK_SCHEMA_COMPAT`, `/readyz` returns 503 and logs `schema_incompatible`. This prevents silent drift.

**Wave 3 contract migration** (REM-09 hardening), as three separate Alembic revisions:
1. Data: delete duplicate `sla_alerts`, keeping `min(id)` per `shipment_id`.
2. `CREATE UNIQUE INDEX CONCURRENTLY uq_sla_alerts_shipment ON shiptrack.sla_alerts (shipment_id)`, inside an `autocommit_block()`.
3. `ALTER TABLE … ADD CONSTRAINT … UNIQUE USING INDEX`.

This is documented in `docs/runbooks/wave-3-contract-migration.md` as the **point of no return** for legacy rollback.

### 9.2 Waves

| Wave | Entry criteria | Actions | Exit criteria | Rollback |
|---|---|---|---|---|
| **0 — Dark launch** | Platform applied; modern cluster + add-ons + release deployed | Weights 0; contract `full` suite with `TARGET=modern`; k6 `baseline` with `TARGET=modern`; contract `ui_parity` check (gate G6) | Contract green; k6 thresholds met; all alarms/dashboards live; Inspector shows no fixable CRITICAL/HIGH | N/A (no traffic) |
| **1 — Read path + UI** | Wave 0 exit, including G6 | Platform PR: `cutover.track` modern 10 → 50 → 100, 30-min soak each. Moves `/api/v1/track/*` and `/ui/*` together; the UI rule is sticky, so existing browser sessions stay on their stack | Platform gates G1–G4 per step; UI stack badge shows `modern` for new sessions | Platform PR or break-glass: `track.modern = 0` |
| **2 — Write path** | Wave 1 at 100%; legacy **v1.1.0** deployed; `migrate_pod_to_s3.py` run on both hosts; PodSync cron installed; **G-POD:** `SELECT count(*) FROM shiptrack.pod_documents WHERE storage_uri LIKE 'file://%' AND uploaded_at < now() - interval '5 minutes'` = 0 (run through the allow-listed `pod-gate` evidence script, legacy §7.6); legacy change freeze on | `cutover.default` modern 10 → 25 → 50 → 100, 30-min soak each | G1–G5; DLQ = 0; simulator ledger `verify` shows 0 lost events for modern-routed traffic; no `pod_not_migrated` event for a POD older than 5 minutes | Weight back to legacy. **Keep workers running** until the events queue drains; S3 PODs are readable by legacy v1.1 |
| **Handoff** | Wave 2 at 100% + 24 h soak | Flip schema ownership (§9.1) | Modern deploy with `migrations.enabled=true` is a no-op at head | Revert flags |
| **3 — Scheduled jobs + decommission** | Handoff complete | 1) SSM: remove `/etc/cron.d/shiptrack-sla` and `shiptrack-podsync` from legacy hosts; 2) Helm: `slaScan.suspend=false`, enable heartbeat alarm; 3) verify exactly one alert per breach; 4) contract migration (§9.1); 5) legacy ASG → 0 (legacy PR); 6) after 7 days, destroy legacy stack and remove tg-legacy routing (platform PR) | Final cost snapshot captured | Before step 4: re-enable legacy cron, suspend CronJob. **After step 4: forward-fix only.** |

### 9.3 Validation evidence per wave
Store everything under `docs/migration/wave-N/`, scrubbed of account IDs, ARNs, DNS names, and tokens before merge (platform §6.12):
- Dashboard screenshots (platform `shiptrack-cutover`)
- Contract JUnit XML
- k6 summaries
- Alarm history export
- Short go/no-go record (who, when, gates, decision)
- UI screenshots showing the stack badge before and after each Wave 1 step

---

## 10. CI/CD

### 10.1 `ci.yml` (pull_request) — parallel jobs, all required

| Job | Steps |
|---|---|
| `test` | `uv sync --frozen`; ruff; mypy; pytest (Postgres 17 service + moto server for AWS APIs); coverage ≥ 75% |
| `web` | `npm ci`; ESLint; `tsc --noEmit`; Vitest; `npm run build`; bundle < 200 KB gzipped; no inline `<script>`/`<style>` in `dist/index.html` |
| `secrets` | gitleaks (full history on first run) |
| `image` | buildx `linux/amd64` load; **Trivy image** `--severity CRITICAL,HIGH --ignore-unfixed --exit-code 1`; Trivy fs (Python and npm dependencies); CycloneDX SBOM artifact |
| `iac` | Per root: `terraform fmt -check`, `init -backend=false`, `validate`, `tflint`; **Checkov** on `terraform/`; `trivy config` |
| `helm` | `helm lint`; `helm template` with `ci-values.yaml` → **kubeconform** `-strict` with CRD schemas for TargetGroupBinding / ScaledObject / TriggerAuthentication (CRDs-catalog); **Checkov** on rendered manifests |

All jobs upload SARIF to GitHub code scanning. Trivy exceptions live in `.trivyignore` with an `# expires: YYYY-MM-DD reason` comment per entry and are mirrored in the findings register.

### 10.2 `release.yml` (push to `dev`, after CI passes)
1. OIDC → `shiptrack-modern-release` (trusts `ref:refs/heads/dev`; ECR push to `shiptrack/app` only).
2. buildx multi-arch → push the per-arch digests. Assert identical `/app/web/dist/assets` listings across architectures and, for the same `web/` tree, against the legacy release's listing; then merge into `sha-<sha>`.
3. Trivy scan of the **pushed digest** (gate).
4. Output the digest.
5. Optional stretch: cosign keyless signing + SBOM attestation.

### 10.3 `deploy.yml` (`workflow_run` on release success, or `workflow_dispatch` with a digest)
- `environment: dev` (required reviewers); `concurrency: deploy-dev` (no cancel)
- Steps:
  1. OIDC → `shiptrack-modern-deploy`
  2. `aws eks update-kubeconfig`
  3. `scripts/render-values.sh`
  4. `helm upgrade --install shiptrack charts/shiptrack -n shiptrack -f values-dev.yaml -f generated-values.yaml --set image.digest=$DIGEST --atomic --wait --timeout 10m --history-max 10`
  5. `kubectl rollout status` for each Deployment
  6. Smoke: platform contract `smoke` suite with `TARGET=modern` and `TEST_TOKEN` from `test_token_secret_arn` (public platform repo checked out at a pinned commit SHA). The suite asserts `X-ShipTrack-Stack: modern`, so a missing token cannot silently test legacy.
  7. Record a GitHub Deployment + annotation (digest, Helm revision, duration)
- **On smoke failure:** `helm rollback shiptrack <previous-revision> --wait` and fail the job. (`--atomic` already covers failures during the upgrade itself.)
- **Gotcha:** a pre-upgrade migration hook is **not** rolled back by `--atomic`/`helm rollback`. Schema changes must be backward compatible (§9.1).
- **DORA evidence:** the workflow emits commit timestamp → deploy-complete timestamp to `docs/migration/dora.csv` via the job summary (manually collected), to compare against the legacy deploy duration.

### 10.4 Terraform workflows
Same pattern as platform §6.11, as a matrix over `cluster` and `addons`. Plan PR comments follow platform §6.12 (addresses and actions only; no plan artifacts). `addons` apply runs only after `cluster` apply succeeds in the same workflow.

---

## 11. Observability and reliability

### 11.1 SLOs (`docs/slo.md`)

| SLO | SLI | Target (28-day) | Source |
|---|---|---|---|
| API availability | 1 − (tg-modern `HTTPCode_Target_5XX_Count` / `RequestCount`) | 99.5% | ALB TG metrics |
| Track latency | Share of `GET /api/v1/track/*` requests < 300 ms | 95% | `http_request_duration_seconds` (AMP) |
| Event freshness | Share of events applied within 60 s of `received_at` | 99% | `shiptrack_event_apply_lag_seconds` (AMP) |

**Burn-rate alarms for availability** (error budget 0.5%), using CloudWatch metric math with composite alarms for AND:
- **Fast:** burn > 14.4× over 1 h **AND** over 5 min → SEV1
- **Slow:** burn > 6× over 6 h **AND** over 30 min → SEV2

Latency and freshness SLOs are tracked in Grafana panels with recording rules (alerting on them is a stretch).

### 11.2 Dashboards
- **CloudWatch `shiptrack-modern-golden-signals`:** tg-modern RED; SQS depth/age (both queues + DLQs); pods and restarts; node CPU/mem (Container Insights); RDS connections; HPA/KEDA replica counts.
- **Grafana** (`observability/grafana/`):
  - App RED by route
  - Event processing results and lag histogram
  - SLA breaches
  - Notifications
  - DB pool
  - SLO burn panels

**Log Insights saved queries:** errors by route; trace by `request_id`; slowest requests; `schema_incompatible` and `pod_not_migrated` events.

### 11.3 Game days — `gamedays/GD-n/README.md`
Each README contains hypothesis, blast radius, steps, expected signals, recovery, and evidence collected.

| ID | Scenario | Injection | Expected detection | Recovery |
|---|---|---|---|---|
| GD-1 | Bad release | Deploy with `FAULT_READY_FAIL=true` | Rollout stalls; readiness gates keep new pods out of the TG; `--atomic` fails | Automatic Helm rollback; evidence: zero 5xx on tg-modern |
| GD-2 | Canary regression | During Wave 2 at 25%: `FAULT_ERROR_RATE=0.05` | Platform `tg-modern-5xx-ratio` (SEV1) and/or fast-burn alarm | Break-glass weight → legacy 100; `helm rollback`; RCA using `request_id` traces |
| GD-3 | Poison message | Send a malformed event body directly to SQS | `events-dlq-visible` alarm | Fix → `aws sqs start-message-move-task` redrive → verify applied (`docs/runbooks/dlq-redrive.md`) |
| GD-4 | Node loss | Terminate one node (or Karpenter spot interruption via AWS FIS **[VERIFY FIS EKS actions]**) | Pod rescheduling; no SLO alarm | Self-healing; evidence: PDB + topology spread held availability; simulator ledger shows 0 lost events |

Ledger verification (GD-3, GD-4, and the Wave 2 and Wave 3 evidence) runs through `evidence.yml` in `shiptrack-legacy` (`ShipTrack-Evidence` on a legacy host) while the legacy ASG exists, because runners cannot reach the private RDS instance. After the legacy ASG is scaled to 0, it runs as a one-shot Kubernetes Job launched by `deploy.yml` (platform §6.4).

---

## 12. Security

- **Checklist:** platform §9 plus:
  - [ ] PSA `restricted` enforced
  - [ ] Every pod non-root with read-only root FS and all capabilities dropped
  - [ ] One IAM role per workload
  - [ ] No Kubernetes Secrets holding DB credentials
  - [ ] Images deployed by digest from an IMMUTABLE ECR repo
  - [ ] Trivy/Checkov/gitleaks/kubeconform gating
  - [ ] Nodes IMDSv2 hop limit 1
  - [ ] Human access via access entries only; no `system:masters` bindings
  - [ ] Every response carries the REM-16 headers; built `index.html` has no inline script or style
- **`docs/security/scan-report.md`** contains:
  - Before (legacy assessment scans) vs after (modern CI + Inspector ECR + Security Hub)
  - Counts by severity
  - Every CRITICAL/HIGH with owner and disposition, cross-referenced to the shared findings register
- **GuardDuty Runtime Monitoring** findings for the cluster are reviewed and recorded.

---

## 13. Cost and optimization

**Measurement method (`docs/cost/analysis.md`):**
- Cost Explorer, daily granularity, grouped by `Stack` tag (requires platform §8 tag activation).
- EKS split cost allocation data for namespace/workload cost.
- **Normalize to cost per 1M requests** at the same k6 load profile. Raw monthly totals are misleading because modern carries fixed costs (EKS control plane, add-ons, AMP).
- **Be explicit:** at this small scale, modern may cost **more** in absolute terms. Report that honestly, then show the optimization trajectory and the crossover at scale.

| ID | Action | Evidence required |
|---|---|---|
| O-M1 | Graviton (arm64) nodes | Same k6 load: node $ and p95 latency, amd64 vs arm64 |
| O-M2 | Spot for workers via Karpenter | Karpenter logs, interruption handled (GD-4), $ delta |
| O-M3 | KEDA scale-to-zero for worker-notify | Replica-hours before/after |
| O-M4 | Right-size requests | Container Insights p95 usage vs requests; VPA in recommendation mode (stretch) |
| O-M5 | Log cost | Drop health-check logs, `INFO` level, 14-day retention: ingestion GB/day before/after |
| O-M6 | ECR lifecycle | Storage GB trend |
| O-M7 | Karpenter consolidation | Node count / utilization before/after |
| O-M8 | SSE-SQS instead of KMS | KMS request count avoided |
| — | Platform O-P1…O-P4 | See platform §10 |

The final presentation requires **at least 3** of these, with numbers.

---

## 14. Risks

| ID | Risk | Mitigation |
|---|---|---|
| M-R1 | Public EKS endpoint open to `0.0.0.0/0` | IAM auth + access entries; enterprise: private endpoint + in-VPC runners |
| M-R2 | Node-level DB SG grants all pods DB reachability | NetworkPolicy; Security Groups for Pods (stretch) |
| M-R3 | DB commit + `PutEvents` dual write | Retries; transactional outbox (stretch) |
| M-R4 | Pre-upgrade migration not rolled back by Helm | Expand/contract discipline; compatibility guard |
| M-R5 | Readiness on DB → ALB fail-open when RDS is down | Documented; RDS alarms are the primary signal |
| M-R6 | Fixed EKS/AMP/add-on costs dominate at small scale | Cost-per-1M normalization; optimization plan |
| M-R7 | Cluster version drifting into extended support | Version pin + upgrade runbook; calendar reminder |
| M-R8 | UI served by the API pods couples UI and API releases | Accepted for scope; roadmap: S3 + CloudFront (§5.11) |
| M-R9 | A POD uploaded to legacy is unreadable through modern for 1–2 minutes (PodSync window) | PodSync every minute under `flock`; G-POD gate; 404 + `pod_not_migrated` log and metric; window ends when Wave 2 reaches 100% (legacy §8) |

---

## 15. Acceptance criteria

1. `docs/FORK.md` exists; the first commit is an unmodified import of legacy `v1.0.0`; every REM appears in at least one commit message.
2. The platform contract `full` suite passes with `TARGET=modern`.
3. Image: multi-arch, non-root, digest-deployed, 0 fixable CRITICAL/HIGH, SBOM produced.
4. Infrastructure and app are deployable from code: `cluster` → `addons` → `helm`; no manual kubectl steps except documented game days.
5. CI gates: test, Trivy, Checkov, gitleaks, kubeconform, TFLint. Deploy uses OIDC + environment approval + `--atomic` + smoke + rollback.
6. A deploy under k6 load produces **zero** tg-modern 5xx (REM-12 evidence).
7. The simulator ledger shows **zero** lost events across a deploy and a node termination (REM-06 evidence).
8. Exactly one `sla_alerts` row per breached shipment after Wave 3 (REM-09 evidence).
9. SLOs, burn-rate alarms, dashboards, and runbooks exist. GD-1…GD-4 have evidence folders.
10. Wave 0–3 evidence is stored per §9.3. The cost analysis contains ≥ 3 optimization actions with numbers.
11. `/ui/` serves the same build as legacy (G6), carries the REM-16 headers, and its stack badge shows `modern`.

---

## 16. Implementation phases

Cross-repo build order is in platform §13. M0–M2 (fork, application, image) are built locally and tested in CI after legacy infrastructure and the platform are complete. M3 onward is applied only through workflows. Legacy v1.1.0 (legacy L6) is built when instructed, as part of M8.

| Phase | Deliverables | Done when |
|---|---|---|
| **M0 Fork** | Import legacy `v1.0.0`; `docs/FORK.md` | Diff vs legacy tag is empty for the imported paths |
| **M1 App refactor** | REM-01, 02, 05, 06, 07, 08, 09 (scan logic), 15, 16 in code; UI static serving (§5.11); §5.9 fault injection; schema compat guard; tests incl. SQS, S3, Secrets Manager, and EventBridge via an AWS API emulator (LocalStack locally, a moto server in CI; the tests take the endpoint from the environment) | pytest green; contract suite green against a local `docker compose` on OrbStack (app + Postgres + LocalStack) |
| **M2 Image** | Dockerfile (including the `web` stage), `.dockerignore` | Builds amd64 + arm64; runs as 10001; Trivy clean; `/ui/` renders from the running container |
| **M3 Terraform cluster** | `terraform/cluster` | validate/tflint/checkov pass; every role has the boundary; SSM outputs defined |
| **M4 Terraform addons** | `terraform/addons` (LBC, KEDA, Grafana, namespace, RBAC) | validate passes; CRs use `kubectl_manifest` |
| **M5 Helm chart** | All templates, schema, values | `helm lint` + kubeconform pass; install on OrbStack's local Kubernetes with stub values succeeds (TGB/KEDA CRDs installed there) |
| **M6 CI/CD** | `ci.yml`, `release.yml`, `deploy.yml`, Terraform workflows | `actionlint` passes; all actions SHA-pinned |
| **M7 Observability** | Alarms, SLO doc, dashboards, Log Insights queries | Every alarm has owner/sev/runbook |
| **M8 Cutover + game days** | Runbooks, `gamedays/`, wave evidence templates | Runbooks are copy-pasteable |
| **M9 Optimization** | Karpenter (NodePools, EC2NodeClass), Graviton, spot workers, scale-to-zero, log tuning, cost analysis template | Plan clean; analysis template has a slot per O-item |
| **M10 Wave 3 contract migration** *(on request)* | Three Alembic revisions + runbook | Tested against a DB containing seeded duplicates |

---

## 17. Verify-at-build-time list

- [x] `terraform-aws-modules/eks` v21 requires AWS provider ≥ 6.0 (confirmed)
- [x] EKS 1.36 in standard support; native `preStop` sleep GA since 1.34 (confirmed)
- [x] `metrics-server` available as an EKS community add-on (confirmed)
- [x] Native arm64 GitHub-hosted runners for public repositories (generally available since August 2025)
- [x] KEDA `podIdentity.provider: aws` (current KEDA docs)
- [ ] Pod Identity with `automountServiceAccountToken: false`
- [ ] AMP managed scraper Terraform resource and scrape-config schema
- [ ] AWS FIS actions for EKS / spot interruption
- [ ] Container Insights enhanced observability pricing model
- [x] EKS 1.36 standard support ends August 2, 2027; extended support ends August 2, 2028 (confirmed)
- [x] Node 24 is Active LTS
- [ ] Current React / Vite majors at build time
- [ ] LocalStack account and auth token (the Community edition ended March 2026); coverage for SQS, S3, Secrets Manager, EventBridge, and KMS (local use only)
