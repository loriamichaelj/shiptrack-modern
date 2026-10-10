# ShipTrack Modern — Architecture Decision Log

Decisions are recorded here, oldest first. Each entry has a status (Planned, Accepted, Superseded) and, once decided, Context, Decision, and Consequences. Entries marked Planned are decisions the design expects to be made during the build.

| # | Title | Status |
|---|---|---|
| 0001 | `fork-strategy` | Accepted; one commit per REM on `dev` amended by ADR-0016 |
| 0002 | `db-connection-budget` | Accepted |
| 0003 | `no-cpu-limits` | Accepted |
| 0004 | `pod-identity-token-automount` | Planned |
| 0005 | `podsync-window-acceptance` | Planned |
| 0006 | `transactional-outbox` | Planned |
| 0007 | `sqs-encryption` | Accepted |
| 0008 | `security-groups-for-pods` | Planned |
| 0009 | `rds-proxy` | Planned |
| 0010 | `ui-serving-and-cloudfront` | Planned |
| 0011 | `ledger-verification-after-legacy` | Planned |
| 0012 | `aws-emulator-in-ci` | Accepted |
| 0013 | `eks-addon-version-pinning` | Accepted |
| 0014 | `pod-restart-alarm-source` | Accepted |
| 0015 | `accepted-trivy-findings-in-the-eks-module` | Accepted |
| 0016 | `squash-merge-and-remediation-history` | Accepted |

## ADR-0001: fork-strategy

**Status:** Accepted

**Context:** Modern must show each anti-pattern being fixed, so a reader has to be able to tell the legacy code from the refactor, and the cutover requires the two stacks to behave identically.

**Decision:** The first commit imports legacy `v1.0.0` unmodified (`docs/FORK.md` records the source). Every later change is a separate commit that names the REM it implements. The API contract (legacy design §3.4) is frozen, with the additions listed in design §1. The UI source in `web/` is not edited until Wave 2 completes, so both stacks serve one UI build.

**Consequences:** `git log` reads as the remediation story, and any REM can be reviewed or reverted alone. The contract suite runs unchanged against both stacks. UI changes wait for Wave 2.

**Amended by ADR-0016:** pull requests are squash-merged, so on `dev` the remediation story is told by pull requests and squash commit bodies rather than one commit per REM. The import commit is unaffected.

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

**Status:** Accepted

**Records:** Requests only, to avoid CFS throttling (design §7.2).

**Context:** A CPU limit makes the kernel throttle a container that has bursts above it, even when the node has idle CPU. The API and workers are bursty and latency-sensitive, and the HPA scales on CPU use measured against the request.

**Decision:** Every container sets a CPU request and a memory limit, and no CPU limit. Requests drive scheduling and the HPA (60% of the request). Memory has a limit because memory is not compressible: a pod that leaks is killed instead of taking the node down with it.

**Consequences:** A busy pod can use idle CPU on its node, and a noisy neighbour is bounded only by requests and the scheduler. Checkov rule CKV_K8S_11 ("CPU limits should be set") is skipped for the rendered chart in `ci.yml` for this reason, and `tests/unit/test_chart.py` fails if a CPU limit appears.

## ADR-0004: pod-identity-token-automount

**Status:** Planned

**Records:** Result of the [VERIFY] on automountServiceAccountToken: false; written either way.

**Context:** Design 7.2 turns off the default service account token for every pod. EKS Pod Identity adds its own projected token volume (audience `pods.eks.amazonaws.com`) and credential environment variables through a mutating webhook, so the default token should not be needed. The documentation does not say outright that the webhook still acts when `automountServiceAccountToken` is false, and there is no cluster yet to test it on.

**Decision:** Provisional: the chart sets `automountServiceAccountToken: false` on the service accounts and pod specs, controlled by `serviceAccount.automountToken` in `values.yaml`. The first deploy decides it. If a pod has no `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` or cannot get credentials, set the value to `true`, deploy, and change this entry to say so.

**Consequences:** Until the first deploy is observed this entry stays Planned. If the token is needed, every pod carries the default token, which gives it a Kubernetes API credential it never uses; the namespace has no Role that grants anything to those service accounts.

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

**Status:** Accepted

**Records:** SSE-SQS vs a CMK (O-M8).

**Context:** Queues can be encrypted with SSE-SQS, which costs nothing, or with a customer managed KMS key, which adds a KMS request charge per API call and a key policy to maintain. The queues carry shipment events and notifications, not secrets.

**Decision:** Both queues and both dead-letter queues use SSE-SQS (`sqs_managed_sse_enabled`). Checkov rule CKV_AWS_27 is skipped inline on each queue with a pointer to this entry. The notifications queue policy allows `events.amazonaws.com` only for the `shiptrack-notify` rule's ARN.

**Consequences:** Messages are encrypted at rest with no extra cost (optimization O-M8). Key use is not logged per request, and access cannot be revoked by disabling a key. Moving to a CMK means adding `kms_master_key_id`, granting the worker and API roles `kms:Decrypt` and `kms:GenerateDataKey` through `sqs`, and letting `events.amazonaws.com` use the key for the notifications queue.

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

## ADR-0015: accepted-trivy-findings-in-the-eks-module

**Status:** Accepted

**Context:** The `iac` job gates on `trivy config` at HIGH and CRITICAL, and it fails on three CRITICAL findings, all raised on resources the `terraform-aws-modules/eks` module creates. AWS-0040 and AWS-0041 are the public API endpoint open to `0.0.0.0/0`, which design §8.1 and risk M-R1 already accept: GitHub-hosted runners have no stable addresses, access is IAM authentication plus access entries, and the private endpoint is always on. AWS-0104 is the node security group's egress-all rule. The module creates it with its recommended rules, which `node_security_group_enable_recommended_rules` turns on or off together, so narrowing egress means declaring every node ingress rule here instead.

**Decision:** The three findings are accepted until 2027-04-10 in `.trivyignore`, each with an `exp:` date that Trivy enforces, and recorded in `docs/security/findings-register.md`. Narrowing egress is not attempted before the first apply, because the replacement rules cannot be tested without a cluster. `eks_public_cidrs` stays the control for the endpoint.

**Consequences:** The gate stays strict for everything else. `.trivyignore` matches by ID, so AWS-0040, AWS-0041, and AWS-0104 are also silenced for any later resource in this repository until the entries expire; a reviewer has to catch a new open security group rule or cluster by eye. When an entry expires the gate fails again, which forces a decision: take over the node rules and restrict egress, move to a private endpoint with in-VPC runners, or renew the acceptance with a new date.

## ADR-0016: squash-merge-and-remediation-history

**Status:** Accepted

**Context:** ADR-0001 expected one commit per REM on `dev`. M1 to M6 were built as eighteen commits, and the repository allows squash, merge, and rebase merges. The owner chose squash for pull request #3 and for the other two repositories, which keeps `dev` linear with one commit per pull request.

**Decision:** Pull requests are squash-merged. The pull request title or the squash commit subject names the REM it implements, and the squash body lists the commits it was built from, as pull request #3 does. The import commit (`4f23aea`) stays a standalone commit on `dev`, so every check in `docs/FORK.md` still holds. The individual commits remain readable on the pull request ref, `refs/pull/<n>/head`.

**Consequences:** On `dev`, M1 to M6 are one commit, so one REM inside it cannot be reverted with `git revert`; it has to be undone by hand. From here, a remediation that may need reverting or reviewing alone is its own pull request. Design §15 criterion 1 (every REM appears in at least one commit message) holds because the squash bodies name them.
