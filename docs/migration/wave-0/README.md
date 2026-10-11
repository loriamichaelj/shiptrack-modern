# Wave 0: dark launch

Modern is deployed and serving, and every weight is 0, so no user request reaches it. The wave
proves modern correct and fast before any traffic moves, and stores the baseline the later gates
compare against. Procedure: platform
[`cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md#wave-0-dark-launch-weights-stay-0).

**Status: exit met with an accepted exception (ADR-0021). The security criterion is not met: 40 fixable findings, 20 distinct, on modern's EKS nodes, accepted until 2026-11-10.**

## Entry

| Criterion | Result |
|---|---|
| Platform applied | Yes |
| Modern cluster, add-ons and release deployed | Yes; the smoke through the ALB passes with `X-ShipTrack-Stack: modern` |
| `cutover.md` and the controls it names exist | Yes (platform ADR-0028) |

## Exit

| Criterion | Result | Evidence |
|---|---|---|
| Contract suite passes against modern (G1) | **Pass**, 53 passed | [`contract-full-modern.txt`](contract-full-modern.txt), run [38155704412](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155704412) |
| Same suite passes against legacy | Pass, 53 passed: the contract describes both stacks | [`contract-full-legacy.txt`](contract-full-legacy.txt), run [38155800708](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155800708) |
| UI build parity (G6) | **Pass** | [`contract-ui-parity-modern.txt`](contract-ui-parity-modern.txt), run [38155769590](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155769590) |
| k6 thresholds met on both stacks (`http_req_failed` < 1%, `p(95)` < 500 ms) | **Pass**: 0.00% failed; p95 50.4 ms legacy and 52.4 ms modern | [`k6-legacy.txt`](k6-legacy.txt) run [38155855171](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155855171); [`k6-modern.txt`](k6-modern.txt) run [38157975440](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38157975440) |
| No fixable CRITICAL or HIGH in modern | **Not met, accepted by ADR-0021**: 40 on the two EKS nodes, 0 in the images | [`findings.md`](findings.md), run [38159470275](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38159470275) |
| Alarms in `OK`, dashboard shows both target groups | Alarms: no SEV1, no SEV2 in ALARM; one alarm is off by design. Dashboard not looked at | [`gates-baseline.md`](gates-baseline.md) |
| Evidence stored here | This folder | |

## Known before wave 1

- **G3 is explained, and is not expected to fail in wave 1.** The aggregate 1.27 comes from one
  route: `POST /events` waits for SQS before it answers (REM-06), 1.15 times legacy at p50 and
  1.51 at p95; track, create and the UI are within 4%. Wave 1 moves only track and the UI. The
  event route moves in wave 2. See [`gates-baseline.md`](gates-baseline.md).
- **The node findings need a rebuilt node image.** [`findings.md`](findings.md) has the table.
- The two baselines ran on different platform commits (legacy on `0dc6c37`, modern on `1685ed1`);
  the k6 scenario did not change between them.

## Decision

Go to wave 1, with one accepted exception. The 20 node-image findings are accepted until 2026-11-10
by [ADR-0021](../../ADR.md#adr-0021-accepted-node-image-findings-until-rebuilt-ami); each wave step
compares the `security-findings.yml` table with that list, and a finding outside it, or any fixable
finding in an application image, stops the step. Two checks are not in this folder: the rollback
rehearsal (platform `rollback-cutover.yml` with `dry_run`) and the dashboard, which is a console
look. Each is recorded in the step record that first depends on it.
