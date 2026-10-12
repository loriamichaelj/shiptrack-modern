# ShipTrack Modern — Architecture Decision Log

Decisions are recorded here, oldest first. Each entry has a status (Planned, Accepted, Superseded) and, once decided, Context, Decision, and Consequences. Entries marked Planned are decisions the design expects to be made during the build.

| # | Title | Status |
|---|---|---|
| 0001 | `fork-strategy` | Accepted; one commit per REM on `dev` amended by ADR-0016 |
| 0002 | `db-connection-budget` | Accepted |
| 0003 | `no-cpu-limits` | Accepted |
| 0004 | `pod-identity-token-automount` | Accepted |
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
| 0017 | `application-signals-auto-monitor-off` | Accepted |
| 0018 | `addons-pr-plan-without-refresh` | Accepted |
| 0019 | `rollout-sampler-during-the-helm-wait` | Accepted |
| 0020 | `waves-gated-by-evidence-not-durations` | Accepted |
| 0021 | `accepted-node-image-findings-until-rebuilt-ami` | Accepted |
| 0022 | `event-route-latency-allowance` | Accepted |
| 0023 | `contract-migration-not-taken` | Accepted |
| 0024 | `modern-ui-is-its-own` | Accepted |
| 0025 | `synthetic-traffic-from-the-browser` | Accepted |
| 0026 | `one-runtime-for-live-and-browse` | Accepted |
| 0027 | `grafana-opens-on-the-alb-with-read-only-viewers` | Accepted |

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

**Consequences:** A busy pod can use idle CPU on its node, and a noisy neighbour is bounded only by requests and the scheduler. Checkov rule CKV_K8S_11 ("CPU limits should be set") is skipped for the rendered chart in `ci-checks.yml` for this reason, and `tests/unit/test_chart.py` fails if a CPU limit appears.

## ADR-0004: pod-identity-token-automount

**Status:** Accepted

**Records:** Result of the [VERIFY] on automountServiceAccountToken: false.

**Context:** Design 7.2 turns off the default service account token for every pod. EKS Pod Identity adds its own projected token volume (audience `pods.eks.amazonaws.com`) and credential environment variables through a mutating webhook, so the default token should not be needed. The documentation does not say outright that the webhook still acts when `automountServiceAccountToken` is false.

**Decision:** The chart keeps `automountServiceAccountToken: false` on the service accounts and pod specs, controlled by `serviceAccount.automountToken` in `values.yaml`. It was observed on the first successful deploy: with the value false, the API pods reached the database, whose credentials the application reads from Secrets Manager with its Pod Identity role, and `/readyz` answered 200 through the ALB. `/readyz` checks the database and the schema revision, so it cannot pass without those credentials.

**Consequences:** No pod carries the default Kubernetes API token it never uses. If a workload ever fails to get credentials, check the Pod Identity association first, and set `serviceAccount.automountToken` to `true` only as a last resort and record it here.

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

**Applied:** The first apply resolved the six add-ons, `check-terraform-outputs.yml` printed them, and they are pinned in `terraform/cluster/terraform.tfvars`. The apply role's next plan showed no add-on change. `terraform-ci.sh` quiets Terraform's output, so the versions are printed by an `outputs` mode of the same script, and by every apply, rather than read from a log.

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

## ADR-0017: application-signals-auto-monitor-off

**Status:** Accepted

**Context:** The first two deploys ran `helm upgrade --atomic --wait` for the full ten minutes and timed out. The rollout sampler (ADR-0019) showed why: no API pod ever existed. The ReplicaSet was refused with `violates PodSecurity "restricted:latest"` for a container named `opentelemetry-auto-instrumentation-java`, which the chart does not define. The CloudWatch Observability add-on injects it: from v5.0.0 Application Signals "Auto monitor" is on by default and brings every Deployment, DaemonSet, and StatefulSet that is mapped to a Kubernetes Service into scope. The API has a Service; the events worker has none and started normally. The injected container sets no `securityContext`, so the `restricted` level refuses the pod.

**Decision:** The add-on's `configuration_values` set `manager.applicationSignals.autoMonitor.monitorAllServices` to `false`, which is the documented way to turn Auto monitor off, and the plan test asserts it. The design takes application metrics from Prometheus (AMP) and alarms from ALB and queue metrics, so Application Signals is not used. Excluding only the `shiptrack` namespace would also work but keeps a feature nothing here needs and bills per signal. Relaxing the namespace below `restricted` would break the security checklist.

**Consequences:** Only the `manager` section is set, so the agent's own defaults and Container Insights are not overridden; Container Insights was not re-checked after the change. If Application Signals is wanted later, enable it for named workloads with `customSelector`, and give the injected containers a compliant `securityContext` or accept a lower Pod Security level for the namespace in a new ADR.

## ADR-0018: addons-pr-plan-without-refresh

**Status:** Accepted

**Context:** Once the addons root had state, every pull request plan of it failed. The plan role reaches the cluster through `AmazonEKSViewPolicy`, which covers neither RBAC roles and role bindings nor Secrets. Refreshing `kubernetes_role_v1.deployer` was forbidden, and because Helm keeps a release as a Secret, the Helm provider could not see the existing releases and planned to create all three again.

**Decision:** `ci-terraform.yml` plans the addons root with `PLAN_REFRESH=false`, which `terraform-ci.sh` turns into `-refresh=false`, and the plan summary says so. The cluster root is planned with a refresh, since the plan role can read everything it manages. The alternative, `AmazonEKSAdminViewPolicy`, lets a pull request triggered role read every Kubernetes Secret, including Helm release values.

**Consequences:** A pull request plan of the addons root shows what the change would do but not drift between state and the cluster; the apply job refreshes in full with the apply role. The plan role also shows a diff of the EKS KMS key policy that the apply role does not: the EKS module makes the identity that runs Terraform the key administrator, so it is a difference between roles and not real drift.

## ADR-0019: rollout-sampler-during-the-helm-wait

**Status:** Accepted

**Context:** `helm upgrade --atomic` uninstalls the release when the wait times out, and the pods, events, and logs go with it. `deploy-app.yml` also sends Helm's output to `/dev/null`, so the first failed deploy left nothing that said why the Deployments never became Ready.

**Decision:** The `Upgrade` step starts `scripts/sample-rollout.sh` in the background before `helm upgrade` and kills it on exit. Every 30 seconds it prints the pods, the target group bindings, the newest events, and, for up to four pods that are not Ready, their conditions, container states, and last 15 log lines. It is read-only, within what the deploy role's namespace Role already allows, and its output is masked for account IDs, ARNs, node names, and instance IDs because the log is public.

**Consequences:** A timed-out deploy leaves evidence, and `--atomic` and the rollback are unchanged. The log carries one block per sample, up to about twenty in a ten minute wait. The sampler depends on the deploy Role keeping `get` and `list` on pods, `pods/log`, events, and target group bindings.

## ADR-0020: waves-gated-by-evidence-not-durations

**Status:** Accepted

**Context:** Design §9 held each weight step for 30 minutes, held wave 2 at 100% for 24 hours before the schema handoff, and destroyed legacy only after 7 days. The decision, made with platform ADR-0030, is that each step is gated by what the gates measure and not by elapsed time, so that the migration can complete in one working session.

**Decision:**
- A step advances when its gates pass over an evidence window in which both target groups saw enough traffic (platform §7). Too little traffic is `NO DATA` and does not advance the step.
- The handoff starts when wave 2 is at 100% with G1 to G5 passing. Legacy is destroyed once wave 3's checks are verified.
- Entry and exit criteria that are not durations are unchanged: G6, G-POD, no fixable CRITICAL or HIGH in modern, zero lost events in the simulator ledger, and the contract migration as the point of no return.

**Consequences:** See platform ADR-0030. The two safety nets that were time-based are gone, so a fault that takes hours to appear is caught by an alarm, not by a step that waited for it. Before the contract migration the rollback is `ops-rollback-cutover.yml` and then the flag reversal in §9.1; after it, forward-fix only.

## ADR-0021: accepted-node-image-findings-until-rebuilt-ami

**Status:** Accepted, until 2026-11-10

**Context:** Wave 0's exit criterion is no fixable CRITICAL or HIGH Inspector finding in modern (§9.2, platform ADR-0029). Run 38159470275 on platform `8472048` found 40: 20 distinct findings, each on both of the two EKS nodes of the `system` node group. All are Go modules compiled into programs the EKS-optimized AL2023 AMI ships (the Go standard library, `x/net`, `x/text`, `x/crypto`, `grpc`, `otel`, the etcd client), so they are fixed when AWS rebuilds those programs and publishes a new AMI, not by anything in this repository. The newest AMI release when the nodes were created was `v20261003` (published 2026-10-08), and the nodes most likely run it. The application images in the `shiptrack/` repository have no fixable finding. Waiting for a rebuilt AMI has no known date.

**Decision:** The owner accepts the 20 findings below on the node image, for the nodes of the `shiptrack` cluster only, until **2026-11-10**, so that cutover wave 1 can start.

| Severity | Finding |
|---|---|
| CRITICAL | CVE-2026-78663 |
| HIGH | CVE-2026-39883, CVE-2026-46600, CVE-2026-56851, CVE-2026-56852, CVE-2026-56854, CVE-2026-56855, CVE-2026-56866, CVE-2026-73500, CVE-2026-78659, CVE-2026-78660, CVE-2026-78662, CVE-2026-78667, CVE-2026-78669, CVE-2026-84304, CVE-2026-84445, CVE-2026-94439, CVE-2026-94440, CVE-2026-97031, GHSA-hrxh-6v49-42gf |

What is not accepted, and still fails the criterion:
- Any fixable CRITICAL or HIGH finding in an application image, or on a resource other than the two nodes.
- Any finding on the nodes whose title is not in the list above. Each wave step compares the `check-security-findings.yml` table with this list.

Conditions:
- **Re-check on every EKS AMI release.** When a release newer than `v20261003` is published, the node group is rolled onto it by a `apply-terraform` and `check-security-findings.yml` is re-run. The acceptance ends the first time the table has none of these findings, and the register row is closed.
- **It expires on 2026-11-10.** After that date the criterion applies in full again. Extending it takes a new ADR that names the findings still open.
- **No other change to the node group** is made under this acceptance.

**Consequences:** Wave 1 can start with a failing `check-security-findings.yml`, which keeps exiting 1 while the findings exist; the wave records say so, and the table is the evidence that nothing outside this list appeared. What the nodes expose is unchanged by this decision: they are in the platform's private application subnets, require IMDSv2 with a hop limit of 1, and carry the workload boundary on their role. The risk accepted is that a Go-library vulnerability in a node binary (`kubelet`, `containerd` or the node tooling) is exploitable on a node before AWS ships a rebuilt image; no traffic reaches modern until wave 1, and then only through the ALB to pods. The exception does not weaken the gate for the application images, which are what the design's "0 fixable CRITICAL/HIGH in deployed images" is about.

## ADR-0022: event-route-latency-allowance

**Status:** Accepted

**Context:** Wave 2, step 2d put every write on modern and the target-group G3 read 1.40 against 1.2 (platform ADR-0031). `POST /events` waits for an SQS send before it answers `202` (REM-06), which is the durability the migration was for; the same-runner run has it at 36.9 ms against 13.4 ms at p95, 23.5 ms more, and every read route within 1.2.

**Decision:** The event route is allowed a p95 of legacy's plus 50 ms (platform ADR-0031). Reducing the gap is a follow-up and does not block the waves.

**Consequences:** Every wave record states G3 per route. A gap over 50 ms on the event route, or over 1.2 times on another route, is a failed G3. Candidates for narrowing it: reuse of the SQS client and its connection, and the region-local endpoint; neither has been measured.

## ADR-0023: contract-migration-not-taken

**Status:** Accepted

**Context:** Design §9.1 ends the migration with a contract migration (modern M10): three Alembic revisions that delete duplicate `sla_alerts` and add a unique constraint on `shipment_id`. It is the point of no return for rolling back to legacy. By the time it would run, the single CronJob with its atomic `UPDATE … RETURNING` already produces one alert per breach: `evidence sla-duplicates` read `alerts=3 shipments=0 extra_alerts=0` after the `contract-sla` test (platform run 38178609695), and had never shown a duplicate. The owner asked that legacy stay a fallback.

**Decision:** The contract migration is not built and not run. Legacy stays running (platform ADR-0032), and rolling back stays possible: `ops-rollback-cutover.yml` sends traffic to legacy, and `ops-legacy-cron.yml restore-sla` puts legacy's SLA cron back.

**Consequences:** "Exactly one alert per breach" holds because there is one scanner and the scan is one atomic statement, not because the database refuses a second row. If legacy's SLA cron is restored for a rollback, modern's CronJob has to be suspended first, or AP-09 returns: two scanners can alert twice. The unique constraint can be added later, after legacy is retired, as the same three revisions.

## ADR-0024: modern-ui-is-its-own

**Status:** Accepted

**Context:** `web/` was forked unchanged from legacy and frozen until wave 2, and gate G6 (platform §7) required both stacks to serve identical hashed asset names, so that a browser sticky to one stack never mixed builds while weights moved. The cutover is complete: modern serves every request and legacy is a fallback on the preview port. The owner asked that legacy's UI stay as it is and that modern's UI be built out with more data, icons, colour, and visuals.

**Decision:**
- Gate G6 is retired (platform ADR-0033). Modern's UI may differ from legacy's.
- Legacy's UI is not changed.
- The UI is built only on the existing API (the contract is still frozen): no endpoint, field, or header is added for it. It keeps the REM-16 CSP: no inline script or style, no `blob:` or `data:` script, same-origin images only.
- The new UI ships as one release and one deploy.

**Consequences:** The two UIs now differ, so opening both shows modern's progress against legacy's original. The contract suite no longer asserts parity; it still asserts that `/ui/` serves the shell and its assets with the right headers on whichever stack it addresses. A browser sticky to legacy sees legacy's UI and one on modern sees modern's, which is the intent while legacy is only a fallback. The UI creates test data when someone uses the create, event, and proof-of-delivery forms; it is not a read-only view.

## ADR-0025: synthetic-traffic-from-the-browser

**Status:** Accepted

**Context:** The owner wanted to watch data moving live through the API, driven by synthetic traffic, instead of a static dashboard. Synthetic load already exists as CI-run tools (the k6 baseline and the carrier simulator), which run from a GitHub runner and print a summary afterwards. Neither can be watched while it runs, and the contract is frozen, so there is no server-side feed to subscribe to.

**Decision:**
- The live page generates the traffic itself, from the browser, through the same public endpoints as any client: create a shipment, send tracking events with an `Idempotency-Key` (some are sent twice), and read the track view. It watches the result of its own calls.
- It uses the carrier `ZZTEST`, which the platform's tests already use for data that is not real.
- It is bounded: 1 to 20 requests a second, 8 in flight, 120 shipments tracked, an automatic stop after 15 minutes, and a stop when the page is left.
- No endpoint, header, or field is added.

**Consequences:** It writes real rows to the shared database, which stay until the platform's `ops-reset-data` (platform ADR-0034) clears the database, because nothing in the API deletes them, and they are isolated only by the carrier code. The numbers are what this browser sees, so latency includes its distance to the load balancer; the apply lag (a `202` to the shipment showing the event) is measured by polling, to a resolution of a few hundred milliseconds. It shows only its own traffic, not other clients'. Throughput is limited by one browser; the k6 baseline remains the way to load the system.

## ADR-0026: one-runtime-for-live-and-browse

**Status:** Accepted

**Context:** The first live page owned its traffic engine, stopped it when the page was left, and kept its shipments to itself, while Browse read its own copy of the list from the server through a page cap. A shipment created on Live was not on Browse until a reload, traffic could not outlive the page, and the System page counted at most the 60 calls its log kept. The owner asked for the pages to agree and for traffic to continue across pages. The owner also asked for the data already in the database to be kept, so nothing is deleted.

**Decision:**
- One runtime, held above the router: the traffic engine and a shipment store. The engine writes what it creates and reads to the store; Browse and System read the store; Browse also reads the server's list into it, all pages, on load and every 15 s. A status is never moved backwards by a late read.
- Traffic is not stopped when a page is left. The header shows it while it runs, with a stop control. A run stops by itself after an hour or after 1,000 shipments created, and its rate follows the clock, so a background tab, whose timers run about once a second, keeps the rate.
- Browse has no page cap and no "load more": its list is complete when the server stops returning a cursor.
- "Fresh at zero" is the live view's: its counters and board start empty and Reset empties them. The shipments already in the database stay and are shown by Browse; the platform's `ops-reset-data` (platform ADR-0034) is what deletes them.
- API call totals are counted separately from the list of recent calls, which keeps 200.

**Consequences:** Browse reads the whole list, so its cost grows with the data: one request per 100 shipments, repeated every 15 s while it is open. The cap of 1,000 created per run bounds what the live traffic adds, and the API deletes no rows, so the list grows until `ops-reset-data` clears it. A second tab runs its own engine and store; the two agree through the server's list within 15 s, and not instantly.

## ADR-0027: grafana-opens-on-the-alb-with-read-only-viewers

**Status:** Accepted

**Context:** Grafana was a ClusterIP service reached with `kubectl port-forward`, and the owner has no `kubectl` or AWS CLI, so the dashboards could not be opened while traffic ran. Only one board existed, and the app's event, SLA, notification, proof-of-delivery, and database metrics had no panels. Platform ADR-0035 opens a listener for Grafana on the ALB, reachable only from the preview addresses.

**Decision:**
- A `TargetGroupBinding`, rendered by the Grafana chart's `extraObjects`, registers the Grafana pods in the platform's `tg-grafana` (the contract's `tg_grafana_arn`), and allows only the ALB's security group to reach port 3000. The service stays ClusterIP and there is no Kubernetes ingress.
- Anonymous visitors are Viewers and there is no login. `viewers_can_edit` is on so a viewer can open Explore, which is the query UI for the managed Prometheus; the provisioned boards are not editable and cannot be deleted or saved over. The admin password stays the chart's random one and is unused.
- The datasource has a fixed uid (`amp`) and a 30 s `timeInterval`, and every panel names that uid and uses `$__rate_interval`, which is four scrapes. The managed collector accepts no interval under 30 s, so a burst of traffic shows within about 30 to 60 s.
- Five boards are provisioned and the traffic board is the home page: live traffic, API RED, event pipeline, proof of delivery and database, service levels.
- The service-level panels read the nearest histogram buckets, `le="0.25"` for the 300 ms track target (the stricter reading) and `le="60.0"` for 60 s of event freshness. The client library renders the bucket label as `60.0`.

**Consequences:** Anyone who can send from a preview address can read the metrics and query them, over plain HTTP. They hold route templates, status classes, and counts, with no tracking numbers or secrets. Process panels (CPU, memory, descriptors) come from the client library's Linux collectors, and the board has nothing for node or pod resource use beyond that: Container Insights and the CloudWatch dashboard cover those. Grafana's data is not persisted, so a restart loses nothing that is not provisioned.
