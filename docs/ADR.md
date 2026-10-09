# ShipTrack Modern — Architecture Decision Log

Decisions are recorded here, oldest first. Each entry has a status (Planned, Accepted, Superseded) and, once decided, Context, Decision, and Consequences. Entries marked Planned are decisions the design expects to be made during the build.

| # | Title | Status |
|---|---|---|
| 0001 | `fork-strategy` | Accepted |
| 0002 | `db-connection-budget` | Accepted |
| 0003 | `no-cpu-limits` | Planned |
| 0004 | `pod-identity-token-automount` | Planned |
| 0005 | `podsync-window-acceptance` | Planned |
| 0006 | `transactional-outbox` | Planned |
| 0007 | `sqs-encryption` | Planned |
| 0008 | `security-groups-for-pods` | Planned |
| 0009 | `rds-proxy` | Planned |
| 0010 | `ui-serving-and-cloudfront` | Planned |
| 0011 | `ledger-verification-after-legacy` | Planned |
| 0012 | `aws-emulator-in-ci` | Accepted |
| 0013 | `eks-addon-version-pinning` | Accepted |
| 0014 | `pod-restart-alarm-source` | Accepted |

## ADR-0001: fork-strategy

**Status:** Accepted

**Context:** Modern must show each anti-pattern being fixed, so a reader has to be able to tell the legacy code from the refactor, and the cutover requires the two stacks to behave identically.

**Decision:** The first commit imports legacy `v1.0.0` unmodified (`docs/FORK.md` records the source). Every later change is a separate commit that names the REM it implements. The API contract (legacy design §3.4) is frozen, with the additions listed in design §1. The UI source in `web/` is not edited until Wave 2 completes, so both stacks serve one UI build.

**Consequences:** `git log` reads as the remediation story, and any REM can be reviewed or reverted alone. The contract suite runs unchanged against both stacks. UI changes wait for Wave 2.

## ADR-0002: db-connection-budget

**Status:** Accepted

**Context:** Legacy and modern share one RDS instance during coexistence, and an HPA or KEDA scale-out can exhaust `max_connections` and take both stacks down. Legacy alone opens up to 120 connections (2 hosts × 4 workers × SQLAlchemy's default 15).

**Decision:** Each workload gets a fixed pool, set through Helm environment (`SHIPTRACK_DB_POOL_SIZE`, `SHIPTRACK_DB_MAX_OVERFLOW`): api 4/2, worker-events 2/0, sla-scan and migrate 1/1, worker-notify none. The worst case during coexistence must stay at or below 60% of `db_max_connections`:

| Consumer | Max replicas | Connections each | Total |
|---|---|---|---|
| legacy app (2 hosts × 4 workers × 15) | | | 120 |
| legacy SLA cron (2 hosts) | | 2 | 4 |
| api | 10 | 6 | 60 |
| worker-events | 10 | 2 | 20 |
| sla-scan and migrate | 1 each | 2 | 4 |
| legacy PodSync (2 hosts) and evidence scripts | | 2 each | 6 |
| **Total** | | | **214** |

The budget is about 240 of about 400 connections on `db.t4g.medium`. Raising an HPA or KEDA maximum or a pool size means redoing this sum. If the result is over the budget, adopt RDS Proxy (ADR-0009) instead of raising the limit.

**Consequences:** The pool sizes are configuration, not code, so they can change without a release. The chart (M5) carries a test that multiplies the pool sizes by the maximum replicas in `values-dev.yaml` and fails when the total passes the budget. The pool is checked with `pool_pre_ping` and recycled every 300 s, which also lets it pick up rotated credentials.

## ADR-0003: no-cpu-limits

**Status:** Planned

**Records:** Requests only, to avoid CFS throttling (design §7.2).

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0004: pod-identity-token-automount

**Status:** Planned

**Records:** Result of the [VERIFY] on automountServiceAccountToken: false; written either way.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0005: podsync-window-acceptance

**Status:** Planned

**Records:** Accepting the 1–2 minute POD window during Wave 2 (M-R9; see legacy ADR podsync-interval-and-window).

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0006: transactional-outbox

**Status:** Planned

**Records:** Decision on the DB commit + PutEvents dual write (M-R3); stretch.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0007: sqs-encryption

**Status:** Planned

**Records:** SSE-SQS vs a CMK (O-M8).

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0008: security-groups-for-pods

**Status:** Planned

**Records:** Node-level DB access vs per-pod (M-R2); stretch.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0009: rds-proxy

**Status:** Planned

**Records:** Written only if the design §5.10 total exceeds the budget.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0010: ui-serving-and-cloudfront

**Status:** Planned

**Records:** UI served by API pods now; S3 + CloudFront as the roadmap (M-R8).

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0011: ledger-verification-after-legacy

**Status:** Planned

**Records:** How simulator verify reaches the database once the legacy hosts are gone (one-shot Kubernetes Job).

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0012: aws-emulator-in-ci

**Status:** Accepted

**Context:** Same constraint as the legacy repo: LocalStack needs an auth token that fork PRs cannot read.

**Decision:** LocalStack locally, a moto server in CI, with the endpoint taken from the environment (see the matching legacy ADR).

**Consequences:** SQS, S3, Secrets Manager, and EventBridge paths are tested without secrets in CI. Features moto does not model (for example EventBridge archive replay) are covered by the game days instead.

## ADR-0013: eks-addon-version-pinning

**Status:** Accepted

**Context:** The design pins the EKS managed add-on versions. Which versions exist for Kubernetes 1.36 can only be listed with `eks:DescribeAddonVersions`, and there are no AWS credentials on the workstation, so they cannot be looked up while writing the code.

**Decision:** `terraform/cluster` takes an `addon_versions` map. An add-on that is not in the map resolves to the newest compatible version when it is first created. The `addon_versions` output prints what each one resolved to, and those values are copied into `terraform.tfvars` after the first apply. From then on every add-on is pinned.

**Consequences:** The first apply is not reproducible by version, and the second plan shows no add-on drift only after the pins are committed. A later upgrade is a pull request that changes one value.

## ADR-0014: pod-restart-alarm-source

**Status:** Accepted

**Context:** Design 8.1 alarms on the Container Insights metric `pod_number_of_container_restarts` for the `shiptrack` namespace. CloudWatch publishes that metric only with the dimensions PodName, Namespace, and ClusterName, so no alarm can cover the namespace, and an alarm cannot use `SEARCH`.

**Decision:** A metric filter on the `performance` log group publishes the largest restart counter among pods in the namespace as `ShipTrack/Modern PodContainerRestarts`. The alarm watches its growth, `RATE(restarts) * 600`, and fires above 3 in ten minutes. The log groups are created by Terraform so the filters have something to attach to and so the groups get 14-day retention and the platform logs key.

**Consequences:** Because the filter publishes a maximum, a restart in one pod can hide a smaller restart count in another during the same period. It is a cheap early warning, not a per-pod record; the per-pod series stay available in Container Insights.
