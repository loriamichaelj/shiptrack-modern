# ShipTrack Modern — Architecture Decision Log

Decisions are recorded here, oldest first. Each entry has a status (Planned, Accepted, Superseded) and, once decided, Context, Decision, and Consequences. Entries marked Planned are decisions the design expects to be made during the build.

| # | Title | Status |
|---|---|---|
| 0001 | `fork-strategy` | Planned |
| 0002 | `db-connection-budget` | Planned |
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

## ADR-0001: fork-strategy

**Status:** Planned

**Records:** Fork from legacy v1.0.0, remediation-per-commit convention, frozen API contract and UI source.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

## ADR-0002: db-connection-budget

**Status:** Planned

**Records:** The design §5.10 arithmetic and the 60% rule.

**Context:** _to be written when decided_

**Decision:** _to be written when decided_

**Consequences:** _to be written when decided_

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
